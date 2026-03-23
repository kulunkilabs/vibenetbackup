from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.device import Device
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.models.job import JobRun, JobStatus

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    device_count = db.query(func.count(Device.id)).scalar()
    enabled_count = db.query(func.count(Device.id)).filter(Device.enabled == True).scalar()
    backup_count = db.query(func.count(Backup.id)).filter(Backup.status == BackupStatus.success).scalar()

    recent_backups = (
        db.query(Backup)
        .filter(Backup.status.in_([BackupStatus.success, BackupStatus.failed, BackupStatus.unchanged]))
        .order_by(Backup.timestamp.desc())
        .limit(14)
        .all()
    )

    # Enrich with device hostname
    device_map = {d.id: d for d in db.query(Device).all()}
    for b in recent_backups:
        b.device_hostname = device_map.get(b.device_id, None)
        if b.device_hostname:
            b.device_hostname = b.device_hostname.hostname

    recent_jobs = (
        db.query(JobRun)
        .order_by(JobRun.started_at.desc())
        .limit(14)
        .all()
    )

    failed_count = (
        db.query(func.count(Backup.id))
        .filter(Backup.status == BackupStatus.failed)
        .scalar()
    )

    destinations = db.query(Destination).order_by(Destination.name).all()

    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "device_count": device_count,
            "enabled_count": enabled_count,
            "backup_count": backup_count,
            "failed_count": failed_count,
            "recent_backups": recent_backups,
            "recent_jobs": recent_jobs,
            "destinations": destinations,
        },
    )
