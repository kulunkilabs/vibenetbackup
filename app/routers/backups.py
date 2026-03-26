import difflib
import io
import json
import os
import tarfile
import zipfile

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.modules.backup_service import run_backup_for_device

router = APIRouter(prefix="/backups")


def _parse_archive_manifest(config_text: str) -> dict | None:
    """Parse a JSON manifest for archive-based backups (zip or tgz)."""
    try:
        data = json.loads(config_text)
        if isinstance(data, dict) and data.get("type") in ("zip", "tgz"):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


@router.get("/")
async def list_backups(
    request: Request,
    page: int = 1,
    per_page: int = 25,
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
):
    if per_page not in (10, 25, 50):
        per_page = 25
    if page < 1:
        page = 1

    query = db.query(Backup)

    # Filter by status
    if status and status in ("success", "failed", "unchanged"):
        query = query.filter(Backup.status == BackupStatus(status))

    # Search by device hostname
    device_map = {d.id: d.hostname for d in db.query(Device).all()}
    if q:
        q_lower = q.strip().lower()
        matching_ids = [did for did, name in device_map.items() if q_lower in name.lower()]
        if matching_ids:
            query = query.filter(Backup.device_id.in_(matching_ids))
        else:
            query = query.filter(Backup.id == -1)  # no results

    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    backups = (
        query
        .order_by(Backup.timestamp.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    for b in backups:
        b.device_hostname = device_map.get(b.device_id, "Unknown")
    return request.app.state.templates.TemplateResponse(
        request, "backups/list.html", {
            "backups": backups,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "q": q,
            "status": status,
        },
    )


@router.post("/batch-delete")
async def batch_delete_backups(
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete multiple backup records and their files on disk."""
    form = await request.form()
    backup_ids = form.getlist("backup_ids")
    if not backup_ids:
        return RedirectResponse(url="/backups", status_code=303)

    for bid in backup_ids:
        try:
            bid_int = int(bid)
        except (ValueError, TypeError):
            continue
        backup = db.query(Backup).get(bid_int)
        if not backup:
            continue
        manifest = _parse_archive_manifest(backup.config_text) if backup.config_text else None
        file_path = manifest.get("path") if manifest else backup.destination_path
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        db.delete(backup)

    db.commit()
    return RedirectResponse(url="/backups", status_code=303)


@router.get("/trigger")
async def trigger_form(request: Request, db: Session = Depends(get_db)):
    devices = db.query(Device).filter(Device.enabled == True).order_by(Device.hostname).all()
    destinations = db.query(Destination).filter(Destination.enabled == True).all()
    return request.app.state.templates.TemplateResponse(
        request, "backups/trigger.html",
        {"devices": devices, "destinations": destinations},
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
    except Exception:
        return HTMLResponse('<span class="badge bg-danger">Backup error</span>')


@router.get("/{backup_id}")
async def backup_detail(backup_id: int, request: Request, db: Session = Depends(get_db)):
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    device = db.query(Device).get(backup.device_id)
    manifest = _parse_archive_manifest(backup.config_text) if backup.config_text else None

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
            if not _parse_archive_manifest(prev_backup.config_text):
                diff_lines = difflib.unified_diff(
                    prev_backup.config_text.splitlines(keepends=True),
                    backup.config_text.splitlines(keepends=True),
                    fromfile=f"Previous ({prev_backup.timestamp})",
                    tofile=f"Current ({backup.timestamp})",
                    lineterm="",
                )
                diff_html = "\n".join(diff_lines)

    return request.app.state.templates.TemplateResponse(
        request,
        "backups/detail.html",
        {
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

    manifest = _parse_archive_manifest(backup.config_text) if backup.config_text else None
    if manifest:
        archive_path = manifest.get("path")
        if not archive_path or not os.path.exists(archive_path):
            raise HTTPException(status_code=404, detail="Archive file not found on disk")
        is_tgz = manifest.get("type") == "tgz"
        ext = ".tar.gz" if is_tgz else ".zip"
        media = "application/gzip" if is_tgz else "application/zip"
        filename = f"{hostname}_{ts}{ext}"
        return StreamingResponse(
            _iter_file(archive_path),
            media_type=media,
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

    manifest = _parse_archive_manifest(backup.config_text) if backup.config_text else None
    if not manifest:
        raise HTTPException(status_code=400, detail="Not an archive backup")

    archive_path = manifest.get("path")
    if not archive_path or not os.path.exists(archive_path):
        raise HTTPException(status_code=404, detail="Archive file not found on disk")

    safe_path = _sanitize_archive_path(path)

    content = _read_from_archive(manifest, archive_path, safe_path)

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

    manifest = _parse_archive_manifest(backup.config_text) if backup.config_text else None
    if not manifest:
        raise HTTPException(status_code=400, detail="Not an archive backup")

    archive_path = manifest.get("path")
    if not archive_path or not os.path.exists(archive_path):
        raise HTTPException(status_code=404, detail="Archive file not found on disk")

    safe_path = _sanitize_archive_path(path)

    content = _read_from_archive(manifest, archive_path, safe_path)
    return PlainTextResponse(content.decode("utf-8", errors="replace"))


@router.post("/{backup_id}/delete")
async def delete_backup(backup_id: int, db: Session = Depends(get_db)):
    """Delete a backup record and its file on disk if it exists."""
    backup = db.query(Backup).get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    # Delete the file on disk
    manifest = _parse_archive_manifest(backup.config_text) if backup.config_text else None
    file_path = manifest.get("path") if manifest else backup.destination_path
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    db.delete(backup)
    db.commit()
    return RedirectResponse(url="/backups", status_code=303)


def _sanitize_archive_path(path: str) -> str:
    """Sanitize a file path for archive member access, preventing traversal."""
    import posixpath
    # Normalize the path and resolve any .. components
    cleaned = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    # Reject if normpath still produced a traversal
    if cleaned.startswith("..") or "/../" in cleaned or cleaned == ".":
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return cleaned


def _read_from_archive(manifest: dict, archive_path: str, member_path: str) -> bytes:
    """Read a single file from a zip or tar.gz archive."""
    if manifest.get("type") == "tgz":
        try:
            with tarfile.open(archive_path, "r:gz") as tf:
                try:
                    member = tf.getmember(member_path)
                except KeyError:
                    raise HTTPException(status_code=404, detail=f"File not found in archive: {member_path}")
                if member.issym():
                    raise HTTPException(status_code=400, detail=f"Cannot view symlink directly: {member_path} -> {member.linkname}")
                f = tf.extractfile(member)
                if f is None:
                    raise HTTPException(status_code=400, detail=f"Cannot extract: {member_path}")
                return f.read()
        except tarfile.TarError:
            raise HTTPException(status_code=500, detail="Corrupted tar.gz archive")
    else:
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if member_path not in zf.namelist():
                    raise HTTPException(status_code=404, detail=f"File not found in archive: {member_path}")
                return zf.read(member_path)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=500, detail="Corrupted ZIP archive")


def _iter_file(path: str, chunk_size: int = 65536):
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk
