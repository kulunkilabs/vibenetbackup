import difflib
import io
import json
import os
import zipfile

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.modules.backup_service import run_backup_for_device

router = APIRouter(prefix="/backups")


def _parse_zip_manifest(config_text: str) -> dict | None:
    try:
        data = json.loads(config_text)
        if isinstance(data, dict) and data.get("type") == "zip":
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


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
    for device_id in device_ids:
        device = db.query(Device).get(device_id)
        if device:
            await run_backup_for_device(db, device)
    return RedirectResponse(url="/backups", status_code=303)


@router.post("/{device_id}/now")
async def backup_now(device_id: int, request: Request, db: Session = Depends(get_db)):
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
    manifest = _parse_zip_manifest(backup.config_text) if backup.config_text else None

    diff_html = None
    prev_backup = None

    if not manifest:
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
        if prev_backup and prev_backup.config_text and backup.config_text:
            if not _parse_zip_manifest(prev_backup.config_text):
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
            "manifest": manifest,
        },
    )


@router.get("/{backup_id}/download")
async def download_backup(backup_id: int, db: Session = Depends(get_db)):
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    device = db.query(Device).get(backup.device_id)
    hostname = device.hostname if device else "backup"
    ts = backup.timestamp.strftime("%Y%m%d_%H%M%S") if backup.timestamp else "unknown"

    manifest = _parse_zip_manifest(backup.config_text) if backup.config_text else None
    if manifest:
        zip_path = manifest.get("path")
        if not zip_path or not os.path.exists(zip_path):
            raise HTTPException(status_code=404, detail="ZIP file not found on disk")
        filename = f"{hostname}_{ts}.zip"
        return StreamingResponse(
            _iter_file(zip_path),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if not backup.config_text:
        raise HTTPException(status_code=404, detail="No backup content available")
    filename = f"{hostname}_{ts}.cfg"
    return PlainTextResponse(
        backup.config_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{backup_id}/file")
async def download_single_file(
    backup_id: int,
    path: str,
    db: Session = Depends(get_db),
):
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    manifest = _parse_zip_manifest(backup.config_text) if backup.config_text else None
    if not manifest:
        raise HTTPException(status_code=400, detail="Not a ZIP backup")

    zip_path = manifest.get("path")
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP file not found on disk")

    safe_path = path.lstrip("/").replace("..", "")
    if not safe_path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if safe_path not in zf.namelist():
                raise HTTPException(status_code=404, detail=f"File not found in archive: {safe_path}")
            content = zf.read(safe_path)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=500, detail="Corrupted ZIP archive")

    filename = os.path.basename(safe_path)
    text_extensions = {".conf", ".cfg", ".ini", ".xml", ".txt", ".yaml", ".yml", ".sh", ""}
    ext = os.path.splitext(filename)[1].lower()
    if ext in text_extensions:
        return PlainTextResponse(
            content.decode("utf-8", errors="replace"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{backup_id}/view-file")
async def view_single_file(
    backup_id: int,
    path: str,
    db: Session = Depends(get_db),
):
    """Return file content as plain text for in-browser modal preview."""
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    manifest = _parse_zip_manifest(backup.config_text) if backup.config_text else None
    if not manifest:
        raise HTTPException(status_code=400, detail="Not a ZIP backup")

    zip_path = manifest.get("path")
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP file not found on disk")

    safe_path = path.lstrip("/").replace("..", "")
    if not safe_path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if safe_path not in zf.namelist():
                raise HTTPException(status_code=404, detail=f"File not found in archive: {safe_path}")
            content = zf.read(safe_path)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=500, detail="Corrupted ZIP archive")

    return PlainTextResponse(content.decode("utf-8", errors="replace"))


@router.post("/{backup_id}/delete")
async def delete_backup(backup_id: int, db: Session = Depends(get_db)):
    """Delete a backup record and its file on disk if it exists."""
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    # Delete the file on disk
    manifest = _parse_zip_manifest(backup.config_text) if backup.config_text else None
    file_path = manifest.get("path") if manifest else backup.destination_path
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    db.delete(backup)
    db.commit()
    return RedirectResponse(url="/backups", status_code=303)


def _iter_file(path: str, chunk_size: int = 65536):
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk
