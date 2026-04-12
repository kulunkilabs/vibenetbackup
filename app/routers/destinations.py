from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.destination import Destination, DestinationType

router = APIRouter(prefix="/destinations")


def _build_config(dest_type: str, form: dict) -> dict:
    """Build config_json from individual form fields based on destination type."""
    if dest_type == "local":
        cfg = {"path": form.get("local_path", "./backups").strip() or "./backups"}
        if form.get("local_compress") == "1":
            cfg["compress"] = True
        return cfg

    if dest_type == "smb":
        cfg = {
            "server": form.get("smb_server", "").strip(),
            "share": form.get("smb_share", "").strip(),
            "base_path": form.get("smb_base_path", "backups").strip() or "backups",
            "username": form.get("smb_username", "").strip(),
            "password": form.get("smb_password", ""),
        }
        if form.get("smb_compress") == "1":
            cfg["compress"] = True
        return cfg

    # Git-based (git, github, gitea, forgejo)
    auth_method = form.get("git_auth_method", "token")
    cfg = {
        "repo_path": form.get("git_repo_path", "./repos/configs").strip() or "./repos/configs",
        "remote_url": form.get("git_remote_url", "").strip(),
        "branch": form.get("git_branch", "main").strip() or "main",
        "auth_method": auth_method,
    }
    if auth_method == "token":
        cfg["token"] = form.get("git_token", "")
    elif auth_method == "ssh":
        cfg["ssh_key_path"] = form.get("git_ssh_key_path", "").strip()
    elif auth_method == "password":
        cfg["username"] = form.get("git_username", "").strip()
        cfg["password"] = form.get("git_password", "")
    return cfg


def _merge_config(old_cfg: dict, new_cfg: dict, dest_type: str) -> dict:
    """Preserve passwords/tokens from old config when form fields are left blank."""
    secret_keys = []
    if dest_type == "smb":
        secret_keys = ["password"]
    elif dest_type in ("git", "github", "gitea", "forgejo"):
        secret_keys = ["token", "password"]

    for key in secret_keys:
        if key in new_cfg and not new_cfg[key] and old_cfg.get(key):
            new_cfg[key] = old_cfg[key]
    return new_cfg


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
    db: Session = Depends(get_db),
):
    form = await request.form()
    name = form.get("name", "").strip()
    dest_type = form.get("dest_type", "local")
    config = _build_config(dest_type, dict(form))

    dest = Destination(
        name=name,
        dest_type=DestinationType(dest_type),
        config_json=config,
        retention_config={
            "daily": int(form.get("retention_daily", 14)),
            "weekly": int(form.get("retention_weekly", 6)),
            "monthly": int(form.get("retention_monthly", 12)),
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
    request: Request,
    db: Session = Depends(get_db),
):
    dest = db.query(Destination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    form = await request.form()
    dest_type = form.get("dest_type", "local")
    config = _build_config(dest_type, dict(form))
    config = _merge_config(dest.config_json or {}, config, dest_type)

    dest.name = form.get("name", "").strip()
    dest.dest_type = DestinationType(dest_type)
    dest.config_json = config
    dest.enabled = form.get("enabled", "true") == "true"
    dest.retention_config = {
        "daily": int(form.get("retention_daily", 14)),
        "weekly": int(form.get("retention_weekly", 6)),
        "monthly": int(form.get("retention_monthly", 12)),
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


@router.get("/{dest_id}/status", response_class=HTMLResponse)
async def destination_status(dest_id: int, db: Session = Depends(get_db)):
    """HTMX endpoint: returns a small status badge for a destination."""
    dest = db.query(Destination).get(dest_id)
    if not dest:
        return HTMLResponse('<span class="badge bg-secondary">?</span>')

    if dest.dest_type.value != "smb":
        return HTMLResponse('<span class="badge bg-secondary text-muted">local</span>')

    from app.modules.destinations.smb import SMBDestination
    backend = SMBDestination()
    result = await backend.test(dest.config_json or {})

    if result["ok"]:
        html = '<span class="badge bg-success"><i class="bi bi-check-circle"></i> Online</span>'
    else:
        # Show which step failed as a tooltip
        failed = next((s for s in result["steps"] if not s["ok"]), None)
        tip = failed["msg"] if failed else "Unknown error"
        tip = tip.replace('"', "&quot;")
        html = f'<span class="badge bg-danger" title="{tip}" data-bs-toggle="tooltip"><i class="bi bi-x-circle"></i> Offline</span>'

    return HTMLResponse(html)


@router.post("/{dest_id}/test")
async def test_destination(dest_id: int, db: Session = Depends(get_db)):
    """Run a full connectivity + write-permission test and return JSON results."""
    dest = db.query(Destination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    if dest.dest_type.value != "smb":
        return JSONResponse({"ok": True, "steps": [{"step": "local", "ok": True, "msg": "Local destination — no connectivity check needed"}]})

    from app.modules.destinations.smb import SMBDestination
    backend = SMBDestination()
    result = await backend.test(dest.config_json or {})
    return JSONResponse(result)
