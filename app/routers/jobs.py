from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.models.job import Schedule, JobRun
from app.models.destination import Destination
from app.modules.scheduler.manager import add_backup_job, remove_backup_job, get_next_run_time

router = APIRouter(prefix="/jobs")


async def _scheduled_backup_runner(schedule_id: int):
    """Callback executed by APScheduler when a schedule fires."""
    from app.database import SessionLocal
    from app.modules.backup_service import run_backup_job

    db = SessionLocal()
    try:
        schedule = db.query(Schedule).get(schedule_id)
        if not schedule or not schedule.enabled:
            return

        device_ids = schedule.device_ids or []
        if not device_ids and schedule.device_group:
            devices = db.query(Device).filter(
                Device.group == schedule.device_group,
                Device.enabled == True,
            ).all()
            device_ids = [d.id for d in devices]

        if not device_ids:
            return

        from datetime import datetime, timezone
        schedule.last_run_at = datetime.now(timezone.utc)
        db.commit()

        await run_backup_job(
            db,
            job_name=schedule.name,
            device_ids=device_ids,
            destination_ids=schedule.destination_ids,
            engine_override=schedule.backup_engine,
            schedule_id=schedule.id,
        )
    finally:
        db.close()


@router.get("/")
async def list_schedules(request: Request, db: Session = Depends(get_db)):
    schedules = db.query(Schedule).order_by(Schedule.name).all()
    for s in schedules:
        s.next_run_at = get_next_run_time(s.id)
    return request.app.state.templates.TemplateResponse(
        "jobs/list.html",
        {"request": request, "schedules": schedules},
    )


@router.get("/add")
async def add_schedule_form(request: Request, db: Session = Depends(get_db)):
    devices = db.query(Device).filter(Device.enabled == True).order_by(Device.hostname).all()
    destinations = db.query(Destination).filter(Destination.enabled == True).all()
    groups = list({d.group for d in db.query(Device).all() if d.group})
    return request.app.state.templates.TemplateResponse(
        "jobs/form.html",
        {
            "request": request,
            "schedule": None,
            "devices": devices,
            "destinations": destinations,
            "groups": groups,
        },
    )


@router.post("/add")
async def add_schedule(
    request: Request,
    name: str = Form(...),
    cron_expression: str = Form(...),
    device_ids: list[int] = Form(None),
    device_group: str = Form(""),
    backup_engine: str = Form(""),
    destination_ids: list[int] = Form(None),
    db: Session = Depends(get_db),
):
    schedule = Schedule(
        name=name,
        cron_expression=cron_expression,
        device_ids=device_ids or [],
        device_group=device_group or None,
        backup_engine=backup_engine or None,
        destination_ids=destination_ids or [],
        enabled=True,
    )
    db.add(schedule)
    db.commit()

    add_backup_job(schedule.id, schedule.cron_expression, _scheduled_backup_runner, schedule_id=schedule.id)

    return RedirectResponse(url="/jobs", status_code=303)


@router.get("/{schedule_id}/edit")
async def edit_schedule_form(schedule_id: int, request: Request, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    devices = db.query(Device).filter(Device.enabled == True).order_by(Device.hostname).all()
    destinations = db.query(Destination).filter(Destination.enabled == True).all()
    groups = list({d.group for d in db.query(Device).all() if d.group})
    return request.app.state.templates.TemplateResponse(
        "jobs/form.html",
        {
            "request": request,
            "schedule": schedule,
            "devices": devices,
            "destinations": destinations,
            "groups": groups,
        },
    )


@router.post("/{schedule_id}/edit")
async def edit_schedule(
    schedule_id: int,
    name: str = Form(...),
    cron_expression: str = Form(...),
    device_ids: list[int] = Form(None),
    device_group: str = Form(""),
    backup_engine: str = Form(""),
    destination_ids: list[int] = Form(None),
    enabled: bool = Form(True),
    db: Session = Depends(get_db),
):
    schedule = db.query(Schedule).get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule.name = name
    schedule.cron_expression = cron_expression
    schedule.device_ids = device_ids or []
    schedule.device_group = device_group or None
    schedule.backup_engine = backup_engine or None
    schedule.destination_ids = destination_ids or []
    schedule.enabled = enabled
    db.commit()

    if enabled:
        add_backup_job(schedule.id, schedule.cron_expression, _scheduled_backup_runner, schedule_id=schedule.id)
    else:
        remove_backup_job(schedule.id)

    return RedirectResponse(url="/jobs", status_code=303)


@router.post("/{schedule_id}/run")
async def run_schedule_now(schedule_id: int, db: Session = Depends(get_db)):
    """Manually trigger a schedule to run immediately."""
    schedule = db.query(Schedule).get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    import asyncio
    asyncio.create_task(_scheduled_backup_runner(schedule_id))
    return RedirectResponse(url="/jobs", status_code=303)


@router.post("/{schedule_id}/delete")
async def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    remove_backup_job(schedule.id)
    db.delete(schedule)
    db.commit()
    return RedirectResponse(url="/jobs", status_code=303)


@router.get("/history")
async def job_history(request: Request, db: Session = Depends(get_db)):
    runs = db.query(JobRun).order_by(JobRun.started_at.desc()).limit(50).all()
    return request.app.state.templates.TemplateResponse(
        "jobs/history.html",
        {"request": request, "runs": runs},
    )


@router.get("/history/{run_id}")
async def job_run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = db.query(JobRun).get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Job run not found")
    from app.models.backup import Backup
    backups = db.query(Backup).filter(Backup.job_run_id == run_id).all()
    device_map = {d.id: d.hostname for d in db.query(Device).all()}
    for b in backups:
        b.device_hostname = device_map.get(b.device_id, "Unknown")
    return request.app.state.templates.TemplateResponse(
        "jobs/run_detail.html",
        {"request": request, "run": run, "backups": backups},
    )
