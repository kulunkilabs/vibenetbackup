"""
Automated database maintenance tasks.

Runs daily via APScheduler:
  - Retention sweep (prune old backup files per GFS policy)
  - Purge old job history records (>90 days)
  - Clean stale in_progress backups (>1 hour old)
  - Purge pruned backup DB records (>90 days, files already deleted)
  - SQLite VACUUM (reclaim disk space)
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models.backup import Backup, BackupStatus
from app.models.job import JobRun

logger = logging.getLogger(__name__)

# How long to keep old records before purging from DB
HISTORY_RETENTION_DAYS = 90
# Backups stuck in_progress longer than this are marked failed
STALE_BACKUP_HOURS = 1


async def run_maintenance() -> dict:
    """Run all maintenance tasks. Called by APScheduler."""
    db = SessionLocal()
    try:
        results = {
            "retention_pruned": 0,
            "retention_errors": 0,
            "job_runs_purged": 0,
            "stale_cleaned": 0,
            "records_purged": 0,
            "vacuumed": False,
        }

        # 1. Retention sweep — prune old backup files
        try:
            from app.modules.retention.manager import run_retention_sweep
            ret = await run_retention_sweep(db)
            results["retention_pruned"] = ret.get("pruned", 0)
            results["retention_errors"] = ret.get("errors", 0)
        except Exception as e:
            logger.error("Maintenance: retention sweep failed: %s", e)

        # 2. Clean stale in_progress backups
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_BACKUP_HOURS)
            stale = db.query(Backup).filter(
                Backup.status == BackupStatus.in_progress,
                Backup.timestamp < cutoff,
            ).all()
            for b in stale:
                b.status = BackupStatus.failed
                b.error_message = "Marked failed by maintenance (stale in_progress)"
            db.commit()
            results["stale_cleaned"] = len(stale)
            if stale:
                logger.info("Maintenance: marked %d stale backups as failed", len(stale))
        except Exception as e:
            logger.error("Maintenance: stale cleanup failed: %s", e)
            db.rollback()

        # 3. Purge old job run records
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)
            old_runs = db.query(JobRun).filter(
                JobRun.started_at < cutoff,
            ).all()
            for run in old_runs:
                db.delete(run)
            db.commit()
            results["job_runs_purged"] = len(old_runs)
            if old_runs:
                logger.info("Maintenance: purged %d job runs older than %d days",
                            len(old_runs), HISTORY_RETENTION_DAYS)
        except Exception as e:
            logger.error("Maintenance: job history purge failed: %s", e)
            db.rollback()

        # 4. Purge old pruned backup records (files already deleted by retention)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)
            old_pruned = db.query(Backup).filter(
                Backup.is_pruned == True,
                Backup.pruned_at < cutoff,
            ).all()
            count = len(old_pruned)
            for b in old_pruned:
                db.delete(b)
            db.commit()
            results["records_purged"] = count
            if count:
                logger.info("Maintenance: purged %d old pruned backup records", count)
        except Exception as e:
            logger.error("Maintenance: pruned record purge failed: %s", e)
            db.rollback()

        # 5. SQLite VACUUM — reclaim disk space
        try:
            with engine.connect() as conn:
                conn.execute(text("VACUUM"))
                conn.commit()
            results["vacuumed"] = True
            logger.info("Maintenance: VACUUM complete")
        except Exception as e:
            logger.error("Maintenance: VACUUM failed: %s", e)

        logger.info(
            "Maintenance complete: retention=%d pruned/%d errors, "
            "stale=%d cleaned, job_runs=%d purged, records=%d purged, vacuum=%s",
            results["retention_pruned"], results["retention_errors"],
            results["stale_cleaned"], results["job_runs_purged"],
            results["records_purged"], results["vacuumed"],
        )
        return results

    finally:
        db.close()
