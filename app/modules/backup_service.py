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


def _resolve_destinations(db: Session, destination_ids: list[int] | None) -> list[Destination]:
    """Enabled Destination rows for the given IDs, or all enabled local
    destinations as a fallback when nothing was selected."""
    destinations: list[Destination] = []
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
    return destinations


def _summarize_results(results: list[tuple[str, str]]) -> tuple[str, str | None]:
    """Pick a comma-joined label and a primary path for a successful multi-dest save.
    Prefers a local path for `destination_path` so in-app Download/Delete keeps
    pointing at the local copy."""
    if not results:
        return "local", None
    types = sorted({t for t, _ in results})
    local_paths = [p for t, p in results if t == "local"]
    primary = local_paths[0] if local_paths else results[0][1]
    return ", ".join(types), primary


async def _handle_binary_backup(
    db: Session,
    device: Device,
    backup: Backup,
    binary_result: tuple[bytes, str, list[str]],
    destination_ids: list[int] | None,
    job_run,
) -> Backup:
    """Save a binary (tar.gz/zip) backup to each selected destination and
    store a JSON manifest in the DB."""
    file_bytes, extension, file_list = binary_result
    archive_type = "tgz" if extension == ".tar.gz" else "zip"
    config_hash = hashlib.sha256(file_bytes).hexdigest()

    destinations = _resolve_destinations(db, destination_ids)

    results: list[tuple[str, str]] = []
    save_errors: list[str] = []
    for dest in destinations:
        dest_type = dest.dest_type.value
        try:
            backend = get_destination(dest_type)
            path = await backend.save_binary(
                hostname=device.hostname,
                data=file_bytes,
                extension=extension,
                config=dest.config_json or {},
            )
            results.append((dest_type, path))
            logger.info(
                "Saved binary backup for %s to %s: %s",
                device.hostname, dest_type, path,
            )
        except NotImplementedError:
            logger.warning(
                "Destination '%s' does not support archive backups — skipping for %s",
                dest_type, device.hostname,
            )
        except Exception as e:
            logger.error(
                "Failed to save binary backup to %s for %s: %s",
                dest_type, device.hostname, e,
            )
            save_errors.append(f"{dest_type}: {e}")

    if not results:
        backup.config_hash = config_hash
        backup.file_size = len(file_bytes)
        backup.status = BackupStatus.failed
        backup.error_message = (
            "Binary backup could not be written to any destination"
            + (": " + "; ".join(save_errors) if save_errors else "")
        )
        db.commit()
        logger.error("Binary backup for %s failed — no destination accepted the archive", device.hostname)
        return backup

    dest_label, primary_path = _summarize_results(results)
    manifest = json.dumps({
        "type": archive_type,
        "path": primary_path,
        "files": sorted(file_list),
        "file_count": len(file_list),
    })

    backup.config_text = manifest
    backup.config_hash = config_hash
    backup.file_size = len(file_bytes)
    backup.destination_type = dest_label
    backup.destination_path = primary_path
    backup.status = BackupStatus.success
    db.commit()

    logger.info(
        "Binary backup complete for %s: %d files, %d bytes, hash=%s..., destinations=%s",
        device.hostname, len(file_list), len(file_bytes), config_hash[:12], dest_label,
    )
    return backup


async def _handle_text_backup(
    db: Session,
    device: Device,
    backup: Backup,
    config_text: str,
    destination_ids: list[int] | None,
) -> Backup:
    """Save a text config backup to each selected destination."""
    config_hash = hashlib.sha256(config_text.encode()).hexdigest()
    destinations = _resolve_destinations(db, destination_ids)

    results: list[tuple[str, str]] = []
    save_errors: list[str] = []
    for dest in destinations:
        dest_type = dest.dest_type.value
        try:
            backend = get_destination(dest_type)
            path = await backend.save(
                hostname=device.hostname,
                config_text=config_text,
                config=dest.config_json or {},
            )
            results.append((dest_type, path))
            logger.info("Saved backup for %s to %s: %s", device.hostname, dest_type, path)
        except Exception as e:
            logger.error("Failed to save to %s for %s: %s", dest_type, device.hostname, e)
            save_errors.append(f"{dest_type}: {e}")

    if destinations and not results:
        backup.config_text = config_text
        backup.config_hash = config_hash
        backup.file_size = len(config_text)
        backup.status = BackupStatus.failed
        backup.error_message = "All destination(s) failed: " + "; ".join(save_errors)
        db.commit()
        logger.error("Backup for %s failed — no destination saved successfully", device.hostname)
        return backup

    if not results:
        # No destinations configured at all — last-resort local save so existing
        # deployments without any enabled destination still produce a file.
        from app.modules.destinations.local import LocalDestination
        local = LocalDestination()
        path = await local.save(
            hostname=device.hostname,
            config_text=config_text,
            config={},
        )
        results.append(("local", path))

    dest_label, primary_path = _summarize_results(results)
    backup.config_text = config_text
    backup.config_hash = config_hash
    backup.file_size = len(config_text)
    backup.destination_type = dest_label
    backup.destination_path = primary_path
    backup.status = BackupStatus.success
    db.commit()

    logger.info(
        "Backup complete for %s: %d bytes, hash=%s..., destinations=%s",
        device.hostname, len(config_text), config_hash[:12], dest_label,
    )
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
