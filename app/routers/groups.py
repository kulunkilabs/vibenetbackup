from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.group import Group
from app.models.destination import Destination
from app.models.notification import NotificationChannel

router = APIRouter(prefix="/groups")


@router.get("/")
async def list_groups(request: Request, db: Session = Depends(get_db)):
    groups = db.query(Group).order_by(Group.name).all()
    destinations = db.query(Destination).order_by(Destination.name).all()
    notifications = db.query(NotificationChannel).order_by(NotificationChannel.name).all()
    # Enrich with destination/notification names for display
    dest_map = {d.id: d.name for d in destinations}
    notif_map = {n.id: n.name for n in notifications}
    for g in groups:
        g.dest_names = [dest_map.get(did, f"#{did}") for did in (g.destination_ids or [])]
        g.notif_names = [notif_map.get(nid, f"#{nid}") for nid in (g.notification_ids or [])]
    engines = [
        ("", "-- Use device default --"),
        ("netmiko", "Netmiko (SSH)"),
        ("scp", "SCP"),
        ("oxidized", "Oxidized"),
        ("pfsense", "pfSense/OPNsense (API)"),
        ("proxmox", "Proxmox VE"),
    ]
    return request.app.state.templates.TemplateResponse(
        request, "groups/list.html", {
            "groups": groups,
            "destinations": destinations,
            "notifications": notifications,
            "engines": engines,
        },
    )


@router.post("/add")
async def add_group(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    backup_engine: str = Form(""),
    db: Session = Depends(get_db),
):
    form = await request.form()
    dest_ids = [int(v) for v in form.getlist("destination_ids")]
    notif_ids = [int(v) for v in form.getlist("notification_ids")]

    name = name.strip()
    if not db.query(Group).filter(Group.name == name).first():
        db.add(Group(
            name=name,
            description=description or None,
            destination_ids=dest_ids or None,
            backup_engine=backup_engine or None,
            notification_ids=notif_ids or None,
        ))
        db.commit()
    return RedirectResponse(url="/groups", status_code=303)


@router.get("/{group_id}/edit")
async def edit_group_form(group_id: int, request: Request, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    if not group:
        return RedirectResponse(url="/groups", status_code=303)
    destinations = db.query(Destination).order_by(Destination.name).all()
    notifications = db.query(NotificationChannel).order_by(NotificationChannel.name).all()
    engines = [
        ("", "-- Use device default --"),
        ("netmiko", "Netmiko (SSH)"),
        ("scp", "SCP"),
        ("oxidized", "Oxidized"),
        ("pfsense", "pfSense/OPNsense (API)"),
        ("proxmox", "Proxmox VE"),
    ]
    return request.app.state.templates.TemplateResponse(
        request, "groups/form.html", {
            "group": group,
            "destinations": destinations,
            "notifications": notifications,
            "engines": engines,
        },
    )


@router.post("/{group_id}/edit")
async def edit_group(
    group_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    backup_engine: str = Form(""),
    db: Session = Depends(get_db),
):
    group = db.query(Group).get(group_id)
    if not group:
        return RedirectResponse(url="/groups", status_code=303)

    form = await request.form()
    dest_ids = [int(v) for v in form.getlist("destination_ids")]
    notif_ids = [int(v) for v in form.getlist("notification_ids")]

    group.name = name.strip()
    group.description = description or None
    group.destination_ids = dest_ids or None
    group.backup_engine = backup_engine or None
    group.notification_ids = notif_ids or None
    db.commit()
    return RedirectResponse(url="/groups", status_code=303)


@router.post("/{group_id}/delete")
async def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    if group:
        db.delete(group)
        db.commit()
    return RedirectResponse(url="/groups", status_code=303)
