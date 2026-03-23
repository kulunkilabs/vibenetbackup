import json
import logging

import httpx
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device, DEVICE_TYPES, oxidized_model_to_device_type
from app.models.credential import Credential
from app.models.backup import Backup, BackupStatus
from app.models.group import Group
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices")

ENGINE_TYPES = {
    "netmiko": "Netmiko (SSH — network devices)",
    "scp": "SCP (Paramiko — file pull via SSH)",
    "oxidized": "Oxidized (REST API)",
    "pfsense": "pfSense / OPNsense (Web API)",
    "proxmox": "Proxmox VE (SFTP — config file backup as .tar.gz)",
}


# ── List & Add (static paths — must come before /{device_id}) ────────


@router.get("/")
async def list_devices(request: Request, db: Session = Depends(get_db)):
    devices = db.query(Device).order_by(Device.hostname).all()
    credentials = db.query(Credential).order_by(Credential.name).all()
    groups = db.query(Group).order_by(Group.name).all()
    return request.app.state.templates.TemplateResponse(
        "devices/list.html",
        {
            "request": request,
            "devices": devices,
            "device_type_labels": DEVICE_TYPES,
            "credentials": credentials,
            "groups": groups,
        },
    )


@router.post("/batch-edit")
async def batch_edit_devices(
    device_ids: str = Form(""),
    credential_id: str = Form(""),
    group: str = Form(""),
    db: Session = Depends(get_db),
):
    ids = [int(x) for x in device_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return RedirectResponse(url="/devices", status_code=303)

    devices = db.query(Device).filter(Device.id.in_(ids)).all()
    for device in devices:
        if credential_id == "__none__":
            device.credential_id = None
        elif credential_id:
            device.credential_id = int(credential_id)
        if group:
            device.group = group
    db.commit()
    return RedirectResponse(url="/devices", status_code=303)


@router.get("/add")
async def add_device_form(request: Request, db: Session = Depends(get_db)):
    credentials = db.query(Credential).order_by(Credential.name).all()
    return request.app.state.templates.TemplateResponse(
        "devices/form.html",
        {
            "request": request,
            "device": None,
            "credentials": credentials,
            "device_types": DEVICE_TYPES,
            "engine_types": ENGINE_TYPES,
            "groups": db.query(Group).order_by(Group.name).all(),
        },
    )


@router.post("/add")
async def add_device(
    request: Request,
    hostname: str = Form(...),
    ip_address: str = Form(...),
    device_type: str = Form("ruckus_fastiron"),
    credential_id: int = Form(None),
    group: str = Form("default"),
    backup_engine: str = Form("netmiko"),
    port: int = Form(22),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    device = Device(
        hostname=hostname,
        ip_address=ip_address,
        device_type=device_type,
        credential_id=credential_id if credential_id else None,
        group=group,
        backup_engine=backup_engine,
        port=port,
        notes=notes or None,
    )
    db.add(device)
    db.commit()
    return RedirectResponse(url=f"/devices/{device.id}", status_code=303)


# ── Test all connections (static path — before /{device_id}) ─────────


@router.get("/test-all")
async def test_all_page(request: Request, db: Session = Depends(get_db)):
    devices = db.query(Device).filter(Device.enabled == True).order_by(Device.hostname).all()
    return request.app.state.templates.TemplateResponse(
        "devices/test_all.html",
        {"request": request, "devices": devices, "device_type_labels": DEVICE_TYPES},
    )


# ── Import from Oxidized (static path — before /{device_id}) ────────


@router.get("/import/oxidized")
async def import_oxidized_form(request: Request, db: Session = Depends(get_db)):
    """Fetch node list from Oxidized and show import form."""
    oxidized_url = get_settings().OXIDIZED_URL.rstrip("/")
    nodes = []
    error = None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{oxidized_url}/nodes.json")
            resp.raise_for_status()
            nodes = resp.json()
    except httpx.ConnectError:
        error = f"Cannot connect to Oxidized at {oxidized_url}"
    except httpx.HTTPStatusError as e:
        error = f"Oxidized returned HTTP {e.response.status_code}"
    except Exception as e:
        error = f"Error fetching from Oxidized: {e}"

    # Mark which nodes already exist in our DB (by IP or hostname)
    existing_ips = {d.ip_address for d in db.query(Device).all()}
    existing_hosts = {d.hostname for d in db.query(Device).all()}
    for node in nodes:
        ip = node.get("ip", "")
        name = node.get("name", "")
        node["already_exists"] = ip in existing_ips or name in existing_hosts
        node["mapped_type"] = oxidized_model_to_device_type(node.get("model", "generic"))
        node["mapped_label"] = DEVICE_TYPES.get(node["mapped_type"], node["mapped_type"])

    credentials = db.query(Credential).order_by(Credential.name).all()

    return request.app.state.templates.TemplateResponse(
        "devices/import_oxidized.html",
        {
            "request": request,
            "nodes": nodes,
            "error": error,
            "oxidized_url": oxidized_url,
            "credentials": credentials,
        },
    )


@router.post("/import/oxidized")
async def import_oxidized_submit(
    request: Request,
    credential_id: int = Form(None),
    backup_engine: str = Form("oxidized"),
    db: Session = Depends(get_db),
):
    """Import selected nodes from Oxidized into the device database."""
    form = await request.form()

    imported = 0
    skipped = 0
    for key, value in form.multi_items():
        if not key.startswith("node_"):
            continue
        try:
            node = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue

        ip = node.get("ip", "").strip()
        name = node.get("name", "").strip()
        model = node.get("model", "generic")
        group = node.get("group", "default") or "default"

        if not ip and not name:
            continue

        exists = db.query(Device).filter(
            (Device.ip_address == ip) | (Device.hostname == name)
        ).first()
        if exists:
            skipped += 1
            continue

        device = Device(
            hostname=name or ip,
            ip_address=ip or name,
            device_type=oxidized_model_to_device_type(model),
            credential_id=credential_id if credential_id else None,
            group=group,
            backup_engine=backup_engine,
            port=22,
            notes=f"Imported from Oxidized (model: {model})",
        )
        db.add(device)
        imported += 1

    db.commit()
    logger.info("Oxidized import: %d imported, %d skipped (already exist)", imported, skipped)

    return RedirectResponse(url="/devices", status_code=303)


# ── Device detail & edit (dynamic /{device_id} paths — MUST be last) ─


@router.get("/{device_id}")
async def device_detail(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    recent_backups = (
        db.query(Backup)
        .filter(Backup.device_id == device_id)
        .order_by(Backup.timestamp.desc())
        .limit(20)
        .all()
    )

    return request.app.state.templates.TemplateResponse(
        "devices/detail.html",
        {
            "request": request,
            "device": device,
            "backups": recent_backups,
            "device_type_labels": DEVICE_TYPES,
        },
    )


@router.get("/{device_id}/clone")
async def clone_device_form(device_id: int, request: Request, db: Session = Depends(get_db)):
    source = db.query(Device).get(device_id)
    if not source:
        raise HTTPException(status_code=404, detail="Device not found")
    credentials = db.query(Credential).order_by(Credential.name).all()
    return request.app.state.templates.TemplateResponse(
        "devices/form.html",
        {
            "request": request,
            "device": None,
            "clone": source,
            "credentials": credentials,
            "device_types": DEVICE_TYPES,
            "engine_types": ENGINE_TYPES,
            "groups": db.query(Group).order_by(Group.name).all(),
        },
    )


@router.get("/{device_id}/edit")
async def edit_device_form(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    credentials = db.query(Credential).order_by(Credential.name).all()
    return request.app.state.templates.TemplateResponse(
        "devices/form.html",
        {
            "request": request,
            "device": device,
            "credentials": credentials,
            "device_types": DEVICE_TYPES,
            "engine_types": ENGINE_TYPES,
            "groups": db.query(Group).order_by(Group.name).all(),
        },
    )


@router.post("/{device_id}/edit")
async def edit_device(
    device_id: int,
    request: Request,
    hostname: str = Form(...),
    ip_address: str = Form(...),
    device_type: str = Form("ruckus_fastiron"),
    credential_id: int = Form(None),
    group: str = Form("default"),
    backup_engine: str = Form("netmiko"),
    port: int = Form(22),
    notes: str = Form(""),
    enabled: bool = Form(True),
    db: Session = Depends(get_db),
):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.hostname = hostname
    device.ip_address = ip_address
    device.device_type = device_type
    device.credential_id = credential_id if credential_id else None
    device.group = group
    device.backup_engine = backup_engine
    device.port = port
    device.notes = notes or None
    device.enabled = enabled
    db.commit()
    return RedirectResponse(url=f"/devices/{device.id}", status_code=303)


@router.post("/{device_id}/delete")
async def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return RedirectResponse(url="/devices", status_code=303)


@router.post("/{device_id}/test")
async def test_device_connection(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.query(Device).get(device_id)
    if not device:
        return HTMLResponse('<span class="badge bg-danger">Device not found</span>')
    if not device.credential:
        return HTMLResponse('<span class="badge bg-warning">No credential assigned</span>')

    from app.modules.engines import get_engine
    engine = get_engine(device.backup_engine)

    try:
        result = await engine.test_connection(device, device.credential)
        if result:
            return HTMLResponse('<span class="badge bg-success">Connection OK</span>')
        else:
            return HTMLResponse('<span class="badge bg-danger">Connection Failed</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="badge bg-danger">Error: {e}</span>')
