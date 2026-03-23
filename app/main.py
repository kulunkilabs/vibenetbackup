import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader

from app.config import get_settings
from app.database import init_db
from app.modules.scheduler.manager import start_scheduler, stop_scheduler
from app.security import require_auth
from app.version import VERSION

logger = logging.getLogger("vibenetbackup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting VIBENetBackup...")

    # Create backup directory
    os.makedirs(settings.BACKUP_DIR, exist_ok=True)

    # Create SSH key directory with restricted permissions
    os.makedirs(settings.SSH_KEY_DIR, mode=0o700, exist_ok=True)

    # Initialize database tables
    init_db()
    logger.info("Database initialized")

    # Create default local destination if none exists
    _ensure_default_destination()

    # Seed default group if none exists
    _ensure_default_group()

    # Start scheduler
    start_scheduler()

    # Re-register any existing schedules
    _reload_schedules()

    logger.info("VIBENetBackup started successfully")
    yield

    # Shutdown
    stop_scheduler()
    logger.info("VIBENetBackup stopped")


def _ensure_default_destination():
    """Seed one destination per type so users can configure and enable them."""
    from app.database import SessionLocal
    from app.models.destination import Destination, DestinationType

    defaults = [
        {
            "name": "Local Storage",
            "dest_type": DestinationType.local,
            "config_json": {"path": get_settings().BACKUP_DIR},
            "enabled": True,
        },
        {
            "name": "Git Repository",
            "dest_type": DestinationType.git,
            "config_json": {
                "repo_path": "./repos/configs",
                "remote_url": "",
                "branch": "main",
                "auth_method": "token",
                "token": "",
            },
            "enabled": False,
        },
        {
            "name": "SMB Share",
            "dest_type": DestinationType.smb,
            "config_json": {
                "server": "",
                "share": "",
                "username": "",
                "password": "",
                "base_path": "backups",
            },
            "enabled": False,
        },
    ]

    db = SessionLocal()
    try:
        for dflt in defaults:
            exists = db.query(Destination).filter(
                Destination.dest_type == dflt["dest_type"]
            ).first()
            if not exists:
                dest = Destination(
                    name=dflt["name"],
                    dest_type=dflt["dest_type"],
                    config_json=dflt["config_json"],
                    retention_config={"daily": 14, "weekly": 6, "monthly": 12},
                    enabled=dflt["enabled"],
                )
                db.add(dest)
                logger.info("Created default destination: %s", dflt["name"])
        db.commit()
    finally:
        db.close()


def _ensure_default_group():
    """Seed the 'default' group if the groups table is empty."""
    from app.database import SessionLocal
    from app.models.group import Group

    db = SessionLocal()
    try:
        if not db.query(Group).first():
            db.add(Group(name="default", description="Default group"))
            db.commit()
            logger.info("Created default group")
    finally:
        db.close()


def _reload_schedules():
    """Re-register all enabled schedules with APScheduler on startup."""
    from app.database import SessionLocal
    from app.models.job import Schedule
    from app.modules.scheduler.manager import add_backup_job
    from app.routers.jobs import _scheduled_backup_runner

    db = SessionLocal()
    try:
        schedules = db.query(Schedule).filter(Schedule.enabled == True).all()
        for s in schedules:
            try:
                add_backup_job(s.id, s.cron_expression, _scheduled_backup_runner, schedule_id=s.id)
            except Exception as e:
                logger.warning("Failed to reload schedule %s: %s", s.name, e)
    finally:
        db.close()


app = FastAPI(
    title="VIBENetBackup",
    description="Network Device Configuration Backup Manager",
    version="1.5.5",
    lifespan=lifespan,
)

# CORS
# Security: Restrict CORS to specific origins
settings = get_settings()
# Parse comma-separated origins from env, default to localhost
cors_origins = getattr(settings, 'CORS_ORIGINS', 'http://localhost:5005,http://127.0.0.1:5005,http://0.0.0.0:5005').split(',')

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# Auth + security headers middleware
@app.middleware("http")
async def auth_and_security_headers(request: Request, call_next):
    from app.security import verify_session_token, verify_credentials, _COOKIE_NAME
    from fastapi.responses import RedirectResponse as _RR
    import base64 as _b64

    path = request.url.path

    # Always allow: login page, static assets, health check
    public = path in ("/login", "/health") or path.startswith("/static/")

    if not public:
        authed = False

        # 1. Session cookie
        token = request.cookies.get(_COOKIE_NAME)
        if token and verify_session_token(token):
            authed = True

        # 2. HTTP Basic (API / curl)
        if not authed:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("basic "):
                try:
                    decoded = _b64.b64decode(auth_header[6:]).decode()
                    u, p = decoded.split(":", 1)
                    if verify_credentials(u, p):
                        authed = True
                except Exception:
                    pass

        if not authed:
            if path.startswith("/api/"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            next_url = request.url.path
            if request.url.query:
                next_url += "?" + request.url.query
            return _RR(url=f"/login?next={next_url}", status_code=302)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'"
    return response

# Remove old Basic-auth dependency (replaced by middleware above)
# app.router.dependencies.append(Depends(require_auth))

# Static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Jinja2 templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
from starlette.templating import Jinja2Templates
app.state.templates = Jinja2Templates(directory=templates_dir)

# Make version available globally in templates
app.state.templates.env.globals["app_version"] = VERSION

# Include routers
from app.routers import dashboard, devices, credentials, backups, jobs, destinations, api, groups

app.include_router(dashboard.router)
app.include_router(devices.router)
app.include_router(credentials.router)
app.include_router(backups.router)
app.include_router(jobs.router)
app.include_router(destinations.router)
app.include_router(api.router)
app.include_router(groups.router)


# ── Login / Logout routes ─────────────────────────────────────────────
from fastapi import Form as FastForm
from fastapi.responses import RedirectResponse as RR
from app.security import verify_credentials, generate_session_token, _COOKIE_NAME, _SESSION_TTL

@app.get("/login")
async def login_page(request: Request, next: str = "/"):
    return app.state.templates.TemplateResponse(
        request, "login.html", {"next": next, "error": None}
    )

@app.post("/login")
async def login_submit(
    request: Request,
    username: str = FastForm(...),
    password: str = FastForm(...),
    remember: str = FastForm(""),
    next: str = FastForm("/"),
):
    if not verify_credentials(username, password):
        return app.state.templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Invalid username or password"},
            status_code=401,
        )
    token = generate_session_token()
    max_age = _SESSION_TTL if remember == "1" else None
    response = RR(url=next if next.startswith("/") else "/", status_code=303)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )
    return response

@app.get("/logout")
async def logout():
    response = RR(url="/login", status_code=303)
    response.delete_cookie(_COOKIE_NAME)
    return response


def cli():
    """Entry point for `vibenetbackup` command and `python -m app.main`."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )


if __name__ == "__main__":
    cli()
