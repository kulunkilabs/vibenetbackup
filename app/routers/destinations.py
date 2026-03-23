import json
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.destination import Destination, DestinationType

router = APIRouter(prefix="/destinations")


@router.get("/")
async def list_destinations(request: Request, db: Session = Depends(get_db)):
    destinations = db.query(Destination).order_by(Destination.name).all()
    return request.app.state.templates.TemplateResponse(
        request, "destinations/list.html", {"destinations": destinations},
    )


@router.get("/add")
async def add_destination_form(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "destinations/form.html",
        {
            "destination": None,
            "dest_types": list(DestinationType),
        },
    )


@router.post("/add")
async def add_destination(
    request: Request,
    name: str = Form(...),
    dest_type: str = Form(...),
    config_json: str = Form("{}"),
    retention_daily: int = Form(14),
    retention_weekly: int = Form(6),
    retention_monthly: int = Form(12),
    db: Session = Depends(get_db),
):
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        config = {}

    dest = Destination(
        name=name,
        dest_type=DestinationType(dest_type),
        config_json=config,
        retention_config={
            "daily": retention_daily,
            "weekly": retention_weekly,
            "monthly": retention_monthly,
        },
    )
    db.add(dest)
    db.commit()
    return RedirectResponse(url="/destinations", status_code=303)


@router.get("/{dest_id}/edit")
async def edit_destination_form(dest_id: int, request: Request, db: Session = Depends(get_db)):
    dest = db.query(Destination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")
    return request.app.state.templates.TemplateResponse(
        request,
        "destinations/form.html",
        {
            "destination": dest,
            "dest_types": list(DestinationType),
        },
    )


@router.post("/{dest_id}/edit")
async def edit_destination(
    dest_id: int,
    name: str = Form(...),
    dest_type: str = Form(...),
    config_json: str = Form("{}"),
    retention_daily: int = Form(14),
    retention_weekly: int = Form(6),
    retention_monthly: int = Form(12),
    enabled: bool = Form(True),
    db: Session = Depends(get_db),
):
    dest = db.query(Destination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        config = {}

    dest.name = name
    dest.dest_type = DestinationType(dest_type)
    dest.config_json = config
    dest.enabled = enabled
    dest.retention_config = {
        "daily": retention_daily,
        "weekly": retention_weekly,
        "monthly": retention_monthly,
    }
    db.commit()
    return RedirectResponse(url="/destinations", status_code=303)


@router.post("/{dest_id}/delete")
async def delete_destination(dest_id: int, db: Session = Depends(get_db)):
    dest = db.query(Destination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")
    db.delete(dest)
    db.commit()
    return RedirectResponse(url="/destinations", status_code=303)
