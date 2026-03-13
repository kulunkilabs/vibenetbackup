import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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


def add_backup_job(sched_id: int, cron_expression: str, func, **kwargs) -> str:
    """Add or replace a scheduled backup job."""
    job_id = f"schedule_{sched_id}"
    parts = cron_expression.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4],
        )
    else:
        trigger = CronTrigger.from_crontab(cron_expression)

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
    except Exception:
        pass


def get_next_run_time(schedule_id: int):
    job_id = f"schedule_{schedule_id}"
    job = scheduler.get_job(job_id)
    if job:
        return job.next_run_time
    return None
