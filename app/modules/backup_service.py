import hashlib
import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.models.job import JobRun, JobStatus
from app.modules.engines import get_engine
from app.modules.destinations import get_destination

logger = logging.getLogger(__name__)


def _resolve_group_profile(db: Session, device: Device):
    """Look up the device's group profile and return (destination_ids, engine) defaults."""
    from app.models.group import Group
    if not device.group:
        return None, None
    group = db.query(Group).filter(Group.name == device.group).first()
    if not group:
        return None, None
    return group.destination_ids, group.backup_engine


async def run_backup_for_device(
    db: Session,
    device: Device,
    destination_ids: list[int] | None = None,
    engine_override: str | None = None,
    job_run: JobRun | None = None,
) -> Backup:
    """Run a single backup for one device. Returns the Backup record."""
    # Resolve group profile defaults (explicit params take priority)
    group_dest_ids, group_engine = _resolve_group_profile(db, device)
    if destination_ids is None and group_dest_ids:
        destination_ids = group_dest_ids
    engine_name = engine_override or group_engine or device.backup_engine
    engine = get_engine(engine_name)

    credential = device.credential
    if not credential:
        backup = Backup(
            device_id=device.id,
            status=BackupStatus.failed,
            error_message="No credential assigned to device",
            job_run_id=job_run.id if job_run else None,
        )
        db.add(backup)
        db.commit()
        return backup

    backup = Backup(
        device_id=device.id,
        status=BackupStatus.in_progress,
        job_run_id=job_run.id if job_run else None,
    )
    db.add(backup)
    db.commit()

    # ── Try binary fetch first (e.g. Proxmox ZIP) ────────────────────
    try:
        binary_result = await engine.fetch_binary(device, credential)
    except Exception as e:
        backup.status = BackupStatus.failed
        backup.error_message = str(e)
        db.commit()
        logger.error("Binary backup failed for %s: %s", device.hostname, e)
        return backup

    if binary_result is not None:
        return await _handle_binary_backup(
            db, device, backup, binary_result, destination_ids, job_run
        )

    # ── Text config fetch (all other engines) ────────────────────────
    try:
        config_text = await engine.fetch_config(device, credential)
    except Exception as e:
        backup.status = BackupStatus.failed
        backup.error_message = str(e)
        db.commit()
        logger.error("Backup failed for %s: %s", device.hostname, e)
        return backup

    return await _handle_text_backup(
        db, device, backup, config_text, destination_ids
    )


async def _handle_binary_backup(
    db: Session,
    device: Device,
    backup: Backup,
    binary_result: tuple[bytes, str, list[str]],
    destination_ids: list[int] | None,
    job_run,
) -> Backup:
    """Save a binary (tar.gz/zip) backup to disk and store a JSON manifest in the DB."""
    file_bytes, extension, file_list = binary_result

    # Determine archive type from extension
    archive_type = "tgz" if extension == ".tar.gz" else "zip"

    config_hash = hashlib.sha256(file_bytes).hexdigest()

    # Save file to local destination
    saved_path = await _save_binary_local(device, file_bytes, extension, destination_ids, db)

    manifest = json.dumps({
        "type": archive_type,
        "path": saved_path,
        "files": sorted(file_list),
        "file_count": len(file_list),
    })

    backup.config_text = manifest
    backup.config_hash = config_hash
    backup.file_size = len(file_bytes)
    backup.destination_type = "local"
    backup.destination_path = saved_path
    backup.status = BackupStatus.success
    db.commit()

    logger.info(
        "Binary backup complete for %s: %d files, %d bytes, hash=%s...",
        device.hostname, len(file_list), len(file_bytes), config_hash[:12],
    )
    return backup


async def _save_binary_local(
    device: Device,
    file_bytes: bytes,
    extension: str,
    destination_ids: list[int] | None,
    db: Session,
) -> str:
    """Save binary file to the local backup directory, return saved path."""
    from app.config import get_settings
    import os

    # Resolve base dir from a configured LOCAL destination only.
    # Binary (archive) backups are currently local-only; non-local destinations
    # (SMB, Git) are not supported for binary payloads and are skipped with a warning.
    base_dir = get_settings().BACKUP_DIR
    if destination_ids:
        dests = db.query(Destination).filter(
            Destination.id.in_(destination_ids),
            Destination.enabled == True,
        ).all()
        local_dest = next((d for d in dests if d.dest_type.value == "local"), None)
        non_local = [d for d in dests if d.dest_type.value != "local"]
        if non_local:
            names = ", ".join(d.dest_type.value for d in non_local)
            logger.warning(
                "Binary/archive backups do not yet support non-local destinations (%s) "
                "for %s — saving locally only.",
                names, device.hostname,
            )
        if local_dest and local_dest.config_json:
            base_dir = local_dest.config_json.get("path", base_dir)

    safe_hostname = os.path.basename(device.hostname.replace("\\", "/")) or "unknown"
    device_dir = os.path.join(base_dir, safe_hostname)
    if not os.path.realpath(device_dir).startswith(os.path.realpath(base_dir)):
        raise ValueError(f"Invalid hostname for path: {device.hostname}")
    os.makedirs(device_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}{extension}"
    filepath = os.path.join(device_dir, filename)

    import asyncio
    await asyncio.to_thread(_write_binary, filepath, file_bytes)

    # Update latest symlink
    latest = os.path.join(device_dir, f"latest{extension}")
    if os.path.islink(latest):
        os.unlink(latest)
    try:
        os.symlink(filepath, latest)
    except OSError:
        pass

    logger.info("Saved binary backup to %s (%d bytes)", filepath, len(file_bytes))
    return filepath


def _write_binary(path: str, content: bytes) -> None:
    with open(path, "wb") as f:
        f.write(content)


async def _handle_text_backup(
    db: Session,
    device: Device,
    backup: Backup,
    config_text: str,
    destination_ids: list[int] | None,
) -> Backup:
    """Save a text config backup (existing flow)."""
    config_hash = hashlib.sha256(config_text.encode()).hexdigest()

    destinations = []
    if destination_ids:
        destinations = db.query(Destination).filter(
            Destination.id.in_(destination_ids),
            Destination.enabled == True,
        ).all()

    if not destinations:
        destinations = db.query(Destination).filter(
            Destination.dest_type == "local",
            Destination.enabled == True,
        ).all()

    saved_path = None
    dest_type = "local"
    save_errors: list[str] = []

    for dest in destinations:
        try:
            backend = get_destination(dest.dest_type.value)
            saved_path = await backend.save(
                hostname=device.hostname,
                config_text=config_text,
                config=dest.config_json or {},
            )
            dest_type = dest.dest_type.value
            logger.info("Saved backup for %s to %s: %s", device.hostname, dest_type, saved_path)
        except Exception as e:
            logger.error("Failed to save to %s for %s: %s", dest.dest_type.value, device.hostname, e)
            save_errors.append(f"{dest.dest_type.value}: {e}")

    if destinations and saved_path is None:
        # Every configured destination failed — do not report success
        backup.config_text = config_text
        backup.config_hash = config_hash
        backup.file_size = len(config_text)
        backup.status = BackupStatus.failed
        backup.error_message = "All destination(s) failed: " + "; ".join(save_errors)
        db.commit()
        logger.error("Backup for %s failed — no destination saved successfully", device.hostname)
        return backup

    if not destinations:
        from app.modules.destinations.local import LocalDestination
        local = LocalDestination()
        saved_path = await local.save(
            hostname=device.hostname,
            config_text=config_text,
            config={},
        )

    backup.config_text = config_text
    backup.config_hash = config_hash
    backup.file_size = len(config_text)
    backup.destination_type = dest_type
    backup.destination_path = saved_path
    backup.status = BackupStatus.success
    db.commit()

    logger.info("Backup complete for %s: %d bytes, hash=%s...", device.hostname, len(config_text), config_hash[:12])
    return backup


async def run_backup_job(
    db: Session,
    job_name: str,
    device_ids: list[int],
    destination_ids: list[int] | None = None,
    engine_override: str | None = None,
    schedule_id: int | None = None,
) -> JobRun:
    """Run a backup job across multiple devices."""
    job_run = JobRun(
        job_name=job_name,
        schedule_id=schedule_id,
        status=JobStatus.running,
        devices_total=len(device_ids),
    )
    db.add(job_run)
    db.commit()

    errors = []
    for device_id in device_ids:
        device = db.get(Device, device_id)
        if not device or not device.enabled:
            job_run.devices_failed += 1
            errors.append(f"Device {device_id}: not found or disabled")
            continue

        try:
            backup = await run_backup_for_device(
                db, device,
                destination_ids=destination_ids,
                engine_override=engine_override,
                job_run=job_run,
            )
            if backup.status == BackupStatus.success:
                job_run.devices_success += 1
            else:
                job_run.devices_failed += 1
                errors.append(f"{device.hostname}: {backup.error_message}")
        except Exception as e:
            job_run.devices_failed += 1
            errors.append(f"{device.hostname}: {e}")

    job_run.completed_at = datetime.now(timezone.utc)
    job_run.status = JobStatus.completed if job_run.devices_failed == 0 else JobStatus.failed
    job_run.error_log = "\n".join(errors) if errors else None
    db.commit()

    logger.info(
        "Job '%s' complete: %d/%d success, %d failed",
        job_name, job_run.devices_success, job_run.devices_total, job_run.devices_failed,
    )

    # Run retention sweep after job
    try:
        from app.modules.retention.manager import run_retention_sweep
        await run_retention_sweep(db)
    except Exception as e:
        logger.error("Post-job retention sweep failed: %s", e)

    # Send notifications
    try:
        from app.modules.notifications import send_job_notifications
        await send_job_notifications(db, job_run)
    except Exception as e:
        logger.error("Failed to send job notifications: %s", e)

    return job_run
