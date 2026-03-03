import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
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

    # Initialize database tables
    init_db()
    logger.info("Database initialized")

    # Create default local destination if none exists
    _ensure_default_destination()

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
    """Create a default local destination if none exists."""
    from app.database import SessionLocal
    from app.models.destination import Destination, DestinationType

    db = SessionLocal()
    try:
        existing = db.query(Destination).filter(Destination.dest_type == DestinationType.local).first()
        if not existing:
            dest = Destination(
                name="Local Storage",
                dest_type=DestinationType.local,
                config_json={"path": get_settings().BACKUP_DIR},
                retention_config={"daily": 14, "weekly": 6, "monthly": 12},
                enabled=True,
            )
            db.add(dest)
            db.commit()
            logger.info("Created default local destination")
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
    version="1.0.0",
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

# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'"
    return response

# Apply authentication to all routes
app.router.dependencies.append(Depends(require_auth))

# Static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Jinja2 templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
from starlette.templating import Jinja2Templates
app.state.templates = Jinja2Templates(directory=templates_dir)

# Make version available globally in templates
app.state.templates.env.globals["app_version"] = VERSION

# Include routers
from app.routers import dashboard, devices, credentials, backups, jobs, destinations, api

app.include_router(dashboard.router)
app.include_router(devices.router)
app.include_router(credentials.router)
app.include_router(backups.router)
app.include_router(jobs.router)
app.include_router(destinations.router)
app.include_router(api.router)


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
