from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.device import Device
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.models.job import JobRun, JobStatus
from app.models.group import Group

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    device_count = db.query(func.count(Device.id)).scalar()
    enabled_count = db.query(func.count(Device.id)).filter(Device.enabled == True).scalar()
    backup_count = db.query(func.count(Backup.id)).filter(Backup.status == BackupStatus.success).scalar()

    recent_backups = (
        db.query(Backup)
        .filter(Backup.status.in_([BackupStatus.success, BackupStatus.failed]))
        .order_by(Backup.timestamp.desc())
        .limit(14)
        .all()
    )

    # Enrich with device hostname and group
    device_map = {d.id: d for d in db.query(Device).all()}
    for b in recent_backups:
        dev = device_map.get(b.device_id)
        b.device_hostname = dev.hostname if dev else None
        b.device_group = dev.group if dev else None

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

    # ── Group overview stats ──────────────────────────────────────
    groups = db.query(Group).order_by(Group.name).all()
    group_names = {g.name for g in groups}
    all_devices = list(device_map.values())

    group_stats = []
    for g in groups:
        g_devices = [d for d in all_devices if d.group == g.name]
        g_device_ids = [d.id for d in g_devices]
        if g_device_ids:
            g_success = db.query(func.count(Backup.id)).filter(
                Backup.device_id.in_(g_device_ids),
                Backup.status == BackupStatus.success,
            ).scalar()
            g_failed = db.query(func.count(Backup.id)).filter(
                Backup.device_id.in_(g_device_ids),
                Backup.status == BackupStatus.failed,
            ).scalar()
            g_last = db.query(func.max(Backup.timestamp)).filter(
                Backup.device_id.in_(g_device_ids),
            ).scalar()
        else:
            g_success = g_failed = 0
            g_last = None
        group_stats.append({
            "name": g.name,
            "device_count": len(g_devices),
            "success": g_success,
            "failed": g_failed,
            "last_backup": g_last,
            "engine": g.backup_engine,
            "has_profile": bool(g.destination_ids or g.backup_engine),
        })

    # Unassigned devices
    unassigned = [d for d in all_devices if not d.group or d.group not in group_names]
    if unassigned:
        u_ids = [d.id for d in unassigned]
        u_success = db.query(func.count(Backup.id)).filter(
            Backup.device_id.in_(u_ids), Backup.status == BackupStatus.success,
        ).scalar()
        u_failed = db.query(func.count(Backup.id)).filter(
            Backup.device_id.in_(u_ids), Backup.status == BackupStatus.failed,
        ).scalar()
        u_last = db.query(func.max(Backup.timestamp)).filter(
            Backup.device_id.in_(u_ids),
        ).scalar()
        group_stats.append({
            "name": "Unassigned",
            "device_count": len(unassigned),
            "success": u_success,
            "failed": u_failed,
            "last_backup": u_last,
            "engine": None,
            "has_profile": False,
        })

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
            "group_stats": group_stats,
        },
    )
