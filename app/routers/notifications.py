from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import NotificationChannel

router = APIRouter(prefix="/notifications")


@router.get("/")
async def list_notifications(request: Request, db: Session = Depends(get_db)):
    channels = db.query(NotificationChannel).order_by(NotificationChannel.name).all()
    return request.app.state.templates.TemplateResponse(
        request, "notifications/list.html", {"channels": channels},
    )


@router.get("/add")
async def add_notification_form(request: Request):
    return request.app.state.templates.TemplateResponse(
        request, "notifications/form.html", {"channel": None},
    )


@router.post("/add")
async def add_notification(
    name: str = Form(...),
    apprise_url: str = Form(...),
    on_success: str = Form(""),
    on_failure: str = Form(""),
    db: Session = Depends(get_db),
):
    ch = NotificationChannel(
        name=name.strip(),
        enabled=True,
        on_success=on_success == "1",
        on_failure=on_failure == "1",
    )
    ch.set_url(apprise_url.strip())
    db.add(ch)
    db.commit()
    return RedirectResponse(url="/notifications", status_code=303)


@router.get("/{channel_id}/edit")
async def edit_notification_form(channel_id: int, request: Request, db: Session = Depends(get_db)):
    ch = db.query(NotificationChannel).get(channel_id)
    if not ch:
        return RedirectResponse(url="/notifications", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request, "notifications/form.html", {"channel": ch},
    )


@router.post("/{channel_id}/edit")
async def edit_notification(
    channel_id: int,
    name: str = Form(...),
    apprise_url: str = Form(""),
    on_success: str = Form(""),
    on_failure: str = Form(""),
    enabled: str = Form("true"),
    db: Session = Depends(get_db),
):
    ch = db.query(NotificationChannel).get(channel_id)
    if not ch:
        return RedirectResponse(url="/notifications", status_code=303)
    ch.name = name.strip()
    ch.on_success = on_success == "1"
    ch.on_failure = on_failure == "1"
    ch.enabled = enabled == "true"
    if apprise_url.strip():
        ch.set_url(apprise_url.strip())
    db.commit()
    return RedirectResponse(url="/notifications", status_code=303)


@router.post("/{channel_id}/delete")
async def delete_notification(channel_id: int, db: Session = Depends(get_db)):
    ch = db.query(NotificationChannel).get(channel_id)
    if ch:
        db.delete(ch)
        db.commit()
    return RedirectResponse(url="/notifications", status_code=303)


@router.post("/{channel_id}/test")
async def test_notification_endpoint(channel_id: int, db: Session = Depends(get_db)):
    ch = db.query(NotificationChannel).get(channel_id)
    if not ch:
        return HTMLResponse('<span class="badge bg-danger">Channel not found</span>')

    from app.modules.notifications import test_notification
    try:
        url = ch.get_url()
    except Exception:
        return HTMLResponse('<span class="badge bg-danger">Failed to decrypt URL</span>')

    ok, msg = await test_notification(url)
    if ok:
        return HTMLResponse(f'<span class="badge bg-success">{msg}</span>')
    return HTMLResponse(f'<span class="badge bg-danger">{msg}</span>')
