"""JSON REST API endpoints for programmatic access."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.models.credential import Credential
from app.models.backup import Backup, BackupStatus
from app.models.job import JobRun, Schedule
from app.models.destination import Destination
from app.schemas.device import DeviceCreate, DeviceUpdate, DeviceRead
from app.schemas.credential import CredentialCreate, CredentialUpdate, CredentialRead
from app.schemas.backup import BackupRead, BackupTrigger
from app.schemas.job import ScheduleCreate, ScheduleRead, JobRunRead
from app.schemas.destination import DestinationCreate, DestinationRead
from app.modules.backup_service import run_backup_for_device, run_backup_job
from app.rate_limiter import get_rate_limit_dependency

router = APIRouter(prefix="/api/v1")

# Apply rate limiting to all API routes (30 requests per minute)
rate_limit = get_rate_limit_dependency(requests_per_minute=30)
router.dependencies.append(Depends(rate_limit))


# --- Devices ---

@router.get("/devices", response_model=list[DeviceRead])
async def api_list_devices(db: Session = Depends(get_db)):
    return db.query(Device).order_by(Device.hostname).all()


@router.post("/devices", response_model=DeviceRead, status_code=201)
async def api_create_device(data: DeviceCreate, db: Session = Depends(get_db)):
    device = Device(**data.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/devices/{device_id}", response_model=DeviceRead)
async def api_get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    return device


@router.put("/devices/{device_id}", response_model=DeviceRead)
async def api_update_device(device_id: int, data: DeviceUpdate, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/devices/{device_id}", status_code=204)
async def api_delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    db.delete(device)
    db.commit()


# --- Credentials ---

@router.get("/credentials", response_model=list[CredentialRead])
async def api_list_credentials(db: Session = Depends(get_db)):
    return db.query(Credential).order_by(Credential.name).all()


@router.post("/credentials", response_model=CredentialRead, status_code=201)
async def api_create_credential(data: CredentialCreate, db: Session = Depends(get_db)):
    cred = Credential(name=data.name, username=data.username, ssh_key_path=data.ssh_key_path)
    if data.password:
        cred.set_password(data.password)
    if data.enable_secret:
        cred.set_enable_secret(data.enable_secret)
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


# --- Backups ---

@router.get("/backups", response_model=list[BackupRead])
async def api_list_backups(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(Backup).order_by(Backup.timestamp.desc()).limit(limit).all()


@router.post("/backups/trigger", response_model=list[BackupRead])
async def api_trigger_backup(data: BackupTrigger, db: Session = Depends(get_db)):
    results = []
    for device_id in data.device_ids:
        device = db.query(Device).get(device_id)
        if not device:
            continue
        backup = await run_backup_for_device(
            db, device,
            destination_ids=data.destination_ids,
            engine_override=data.engine_override,
        )
        results.append(backup)
    return results


@router.get("/backups/{backup_id}", response_model=BackupRead)
async def api_get_backup(backup_id: int, db: Session = Depends(get_db)):
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(404, "Backup not found")
    return backup


# --- Schedules ---

@router.get("/schedules", response_model=list[ScheduleRead])
async def api_list_schedules(db: Session = Depends(get_db)):
    return db.query(Schedule).order_by(Schedule.name).all()


@router.post("/schedules", response_model=ScheduleRead, status_code=201)
async def api_create_schedule(data: ScheduleCreate, db: Session = Depends(get_db)):
    schedule = Schedule(**data.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


# --- Job Runs ---

@router.get("/jobs", response_model=list[JobRunRead])
async def api_list_job_runs(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(JobRun).order_by(JobRun.started_at.desc()).limit(limit).all()


# --- Destinations ---

@router.get("/destinations", response_model=list[DestinationRead])
async def api_list_destinations(db: Session = Depends(get_db)):
    return db.query(Destination).order_by(Destination.name).all()


@router.post("/destinations", response_model=DestinationRead, status_code=201)
async def api_create_destination(data: DestinationCreate, db: Session = Depends(get_db)):
    dest = Destination(**data.model_dump())
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return dest


# --- Retention ---

@router.post("/retention/sweep")
async def api_retention_sweep(db: Session = Depends(get_db)):
    from app.modules.retention.manager import run_retention_sweep
    results = await run_retention_sweep(db)
    return results


# --- Maintenance ---

@router.post("/maintenance/run")
async def api_run_maintenance():
    """Run full DB maintenance: retention, cleanup, VACUUM."""
    from app.modules.maintenance import run_maintenance
    results = await run_maintenance()
    return results
