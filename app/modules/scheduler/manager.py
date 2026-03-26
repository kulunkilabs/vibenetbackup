import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    job_defaults={"misfire_grace_time": 3600, "coalesce": True},
)


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


def validate_cron_expression(cron_expression: str) -> CronTrigger:
    """Parse and validate a cron expression, returning a CronTrigger or raising ValueError."""
    parts = cron_expression.strip().split()
    try:
        if len(parts) == 5:
            return CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4],
            )
        else:
            return CronTrigger.from_crontab(cron_expression)
    except (ValueError, KeyError) as e:
        raise ValueError(f"Invalid cron expression '{cron_expression}': {e}") from e


def add_backup_job(sched_id: int, cron_expression: str, func, **kwargs) -> str:
    """Add or replace a scheduled backup job."""
    job_id = f"schedule_{sched_id}"
    trigger = validate_cron_expression(cron_expression)

    scheduler.add_job(
        func, trigger=trigger, id=job_id, replace_existing=True,
        kwargs=kwargs,
    )
    logger.info("Added scheduled job %s with cron '%s'", job_id, cron_expression)
    return job_id


def remove_backup_job(schedule_id: int) -> None:
    job_id = f"schedule_{schedule_id}"
    try:
        scheduler.remove_job(job_id)
        logger.info("Removed scheduled job %s", job_id)
    except JobLookupError:
        logger.debug("Job %s not found in scheduler (already removed)", job_id)
    except Exception as e:
        logger.warning("Failed to remove scheduled job %s: %s", job_id, e)


def get_next_run_time(schedule_id: int):
    job_id = f"schedule_{schedule_id}"
    job = scheduler.get_job(job_id)
    if job:
        return job.next_run_time
    return None
