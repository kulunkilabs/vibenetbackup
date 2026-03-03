import difflib
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.modules.backup_service import run_backup_for_device

router = APIRouter(prefix="/backups")


@router.get("/")
async def list_backups(request: Request, db: Session = Depends(get_db)):
    backups = (
        db.query(Backup)
        .order_by(Backup.timestamp.desc())
        .limit(100)
        .all()
    )
    device_map = {d.id: d.hostname for d in db.query(Device).all()}
    for b in backups:
        b.device_hostname = device_map.get(b.device_id, "Unknown")
    return request.app.state.templates.TemplateResponse(
        "backups/list.html",
        {"request": request, "backups": backups},
    )


@router.get("/trigger")
async def trigger_form(request: Request, db: Session = Depends(get_db)):
    devices = db.query(Device).filter(Device.enabled == True).order_by(Device.hostname).all()
    destinations = db.query(Destination).filter(Destination.enabled == True).all()
    return request.app.state.templates.TemplateResponse(
        "backups/trigger.html",
        {"request": request, "devices": devices, "destinations": destinations},
    )


@router.post("/trigger")
async def trigger_backup(
    request: Request,
    device_ids: list[int] = Form(...),
    db: Session = Depends(get_db),
):
    results = []
    for device_id in device_ids:
        device = db.query(Device).get(device_id)
        if not device:
            continue
        backup = await run_backup_for_device(db, device)
        results.append(backup)
    return RedirectResponse(url="/backups", status_code=303)


@router.post("/{device_id}/now")
async def backup_now(device_id: int, request: Request, db: Session = Depends(get_db)):
    """HTMX endpoint to trigger a single device backup."""
    device = db.query(Device).get(device_id)
    if not device:
        return HTMLResponse('<span class="badge bg-danger">Device not found</span>')

    try:
        backup = await run_backup_for_device(db, device)
        if backup.status == BackupStatus.success:
            return HTMLResponse(f'<span class="badge bg-success">Backup OK ({backup.file_size} bytes)</span>')
        elif backup.status == BackupStatus.unchanged:
            return HTMLResponse('<span class="badge bg-info">Config unchanged</span>')
        else:
            return HTMLResponse(f'<span class="badge bg-danger">Failed: {backup.error_message}</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="badge bg-danger">Error: {e}</span>')


@router.get("/{backup_id}")
async def backup_detail(backup_id: int, request: Request, db: Session = Depends(get_db)):
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    device = db.query(Device).get(backup.device_id)

    # Get previous backup for diff
    prev_backup = (
        db.query(Backup)
        .filter(
            Backup.device_id == backup.device_id,
            Backup.id < backup.id,
            Backup.status.in_([BackupStatus.success, BackupStatus.unchanged]),
        )
        .order_by(Backup.timestamp.desc())
        .first()
    )

    diff_html = None
    if prev_backup and prev_backup.config_text and backup.config_text:
        diff_lines = difflib.unified_diff(
            prev_backup.config_text.splitlines(keepends=True),
            backup.config_text.splitlines(keepends=True),
            fromfile=f"Previous ({prev_backup.timestamp})",
            tofile=f"Current ({backup.timestamp})",
            lineterm="",
        )
        diff_html = "\n".join(diff_lines)

    return request.app.state.templates.TemplateResponse(
        "backups/detail.html",
        {
            "request": request,
            "backup": backup,
            "device": device,
            "diff_html": diff_html,
            "prev_backup": prev_backup,
        },
    )


@router.get("/{backup_id}/download")
async def download_backup(backup_id: int, db: Session = Depends(get_db)):
    backup = db.query(Backup).get(backup_id)
    if not backup or not backup.config_text:
        raise HTTPException(status_code=404, detail="Backup not found")
    device = db.query(Device).get(backup.device_id)
    filename = f"{device.hostname}_{backup.timestamp.strftime('%Y%m%d_%H%M%S')}.cfg" if device else "backup.cfg"
    return PlainTextResponse(
        backup.config_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
