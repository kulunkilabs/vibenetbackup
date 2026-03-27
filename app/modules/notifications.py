import logging
from sqlalchemy.orm import Session

from app.models.notification import NotificationChannel
from app.models.job import JobRun

logger = logging.getLogger(__name__)


async def send_job_notifications(db: Session, job_run: JobRun) -> None:
    """Send Apprise notifications for a completed job run."""
    try:
        import apprise
    except ImportError:
        logger.debug("apprise not installed, skipping notifications")
        return

    channels = db.query(NotificationChannel).filter(
        NotificationChannel.enabled == True,
    ).all()

    if not channels:
        return

    has_failures = job_run.devices_failed > 0
    is_success = job_run.devices_failed == 0

    urls = []
    for ch in channels:
        if (is_success and ch.on_success) or (has_failures and ch.on_failure):
            try:
                urls.append(ch.get_url())
            except Exception as e:
                logger.warning("Failed to decrypt URL for channel %s: %s", ch.name, e)

    if not urls:
        return

    apobj = apprise.Apprise()
    for url in urls:
        apobj.add(url)

    if is_success:
        title = f"Backup OK: {job_run.job_name}"
        notify_type = apprise.NotifyType.SUCCESS
    else:
        title = f"Backup FAILED: {job_run.job_name}"
        notify_type = apprise.NotifyType.FAILURE

    body_lines = [
        f"Job: {job_run.job_name}",
        f"Devices: {job_run.devices_success}/{job_run.devices_total} success, {job_run.devices_failed} failed",
    ]
    if job_run.error_log:
        # Truncate long error logs for notifications
        errors = job_run.error_log[:500]
        body_lines.append(f"\nErrors:\n{errors}")

    body = "\n".join(body_lines)

    try:
        await apobj.async_notify(title=title, body=body, notify_type=notify_type)
        logger.info("Sent notifications for job '%s' to %d channels", job_run.job_name, len(urls))
    except Exception as e:
        logger.error("Failed to send notifications: %s", e)


async def test_notification(url: str) -> tuple[bool, str]:
    """Send a test notification to validate the Apprise URL. Returns (success, message)."""
    try:
        import apprise
    except ImportError:
        return False, "apprise package is not installed"

    apobj = apprise.Apprise()
    if not apobj.add(url):
        return False, "Invalid Apprise URL"

    try:
        results = await apobj.async_notify(
            title="VIBENetBackup Test",
            body="This is a test notification from VIBENetBackup.",
            notify_type=apprise.NotifyType.INFO,
        )
        if results:
            return True, "Test notification sent successfully"
        return False, "Notification delivery failed"
    except Exception as e:
        return False, str(e)
