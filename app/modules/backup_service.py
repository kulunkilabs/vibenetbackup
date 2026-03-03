import hashlib
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.credential import Credential
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.models.job import JobRun, JobStatus
from app.modules.engines import get_engine
from app.modules.destinations import get_destination

logger = logging.getLogger(__name__)


async def run_backup_for_device(
    db: Session,
    device: Device,
    destination_ids: list[int] | None = None,
    engine_override: str | None = None,
    job_run: JobRun | None = None,
) -> Backup:
    """Run a single backup for one device. Returns the Backup record."""
    engine_name = engine_override or device.backup_engine
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

    # Fetch config
    backup = Backup(
        device_id=device.id,
        status=BackupStatus.in_progress,
        job_run_id=job_run.id if job_run else None,
    )
    db.add(backup)
    db.commit()

    try:
        config_text = await engine.fetch_config(device, credential)
    except Exception as e:
        backup.status = BackupStatus.failed
        backup.error_message = str(e)
        db.commit()
        logger.error("Backup failed for %s: %s", device.hostname, e)
        return backup

    # Compute hash for change detection
    config_hash = hashlib.sha256(config_text.encode()).hexdigest()

    # Check if config has changed since last backup
    last_backup = (
        db.query(Backup)
        .filter(
            Backup.device_id == device.id,
            Backup.status == BackupStatus.success,
            Backup.id != backup.id,
        )
        .order_by(Backup.timestamp.desc())
        .first()
    )

    if last_backup and last_backup.config_hash == config_hash:
        backup.status = BackupStatus.unchanged
        backup.config_hash = config_hash
        backup.config_text = config_text
        backup.file_size = len(config_text)
        db.commit()
        logger.info("Config unchanged for %s (hash: %s...)", device.hostname, config_hash[:12])
        return backup

    # Save to destinations
    destinations = []
    if destination_ids:
        destinations = db.query(Destination).filter(
            Destination.id.in_(destination_ids),
            Destination.enabled == True,
        ).all()

    if not destinations:
        # Default: save to local
        destinations = db.query(Destination).filter(
            Destination.dest_type == "local",
            Destination.enabled == True,
        ).all()

    saved_path = None
    dest_type = "local"

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

    # If no destinations configured, save locally with defaults
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
        device = db.query(Device).get(device_id)
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
            if backup.status == BackupStatus.success or backup.status == BackupStatus.unchanged:
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
    return job_run
