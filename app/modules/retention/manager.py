import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.backup import Backup, BackupStatus
from app.models.destination import Destination
from app.modules.destinations import get_destination

logger = logging.getLogger(__name__)


def compute_backups_to_prune(
    backups: list[Backup],
    daily: int = 14,
    weekly: int = 6,
    monthly: int = 12,
) -> list[Backup]:
    """
    Compute which backups should be pruned using a GFS-like policy.
    Keeps: `daily` most recent daily, `weekly` weekly, `monthly` monthly backups.
    """
    try:
        from grandfatherson import to_delete, DAILY, WEEKLY, MONTHLY
        dates = [b.timestamp for b in backups if b.timestamp]
        if not dates:
            return []
        delete_dates = set(to_delete(
            dates,
            days=daily,
            weeks=weekly,
            months=monthly,
        ))
        return [b for b in backups if b.timestamp in delete_dates]
    except ImportError:
        logger.warning("grandfatherson not installed, using simple count-based retention")
        # Fallback: keep last N backups
        keep_count = daily + weekly + monthly
        sorted_backups = sorted(backups, key=lambda b: b.timestamp or datetime.min, reverse=True)
        return sorted_backups[keep_count:]


async def run_retention_sweep(db: Session) -> dict:
    """Run retention sweep across all destinations with retention configs."""
    results = {"pruned": 0, "errors": 0}
    destinations = db.query(Destination).filter(Destination.retention_config.isnot(None)).all()

    for dest in destinations:
        rc = dest.retention_config or {}
        daily = rc.get("daily", 14)
        weekly = rc.get("weekly", 6)
        monthly = rc.get("monthly", 12)

        # Get unpruned successful backups for this destination type
        backups = (
            db.query(Backup)
            .filter(
                Backup.destination_type == dest.dest_type.value,
                Backup.status == BackupStatus.success,
                Backup.is_pruned == False,
            )
            .order_by(Backup.timestamp.asc())
            .all()
        )

        # Group by device
        by_device: dict[int, list[Backup]] = {}
        for b in backups:
            by_device.setdefault(b.device_id, []).append(b)

        backend = get_destination(dest.dest_type.value)

        for device_id, device_backups in by_device.items():
            to_prune = compute_backups_to_prune(device_backups, daily, weekly, monthly)
            for backup in to_prune:
                try:
                    if backup.destination_path:
                        await backend.delete(backup.destination_path, dest.config_json or {})
                    backup.is_pruned = True
                    backup.pruned_at = datetime.now(timezone.utc)
                    results["pruned"] += 1
                except Exception as e:
                    logger.error("Retention: failed to prune backup %d: %s", backup.id, e)
                    results["errors"] += 1

    db.commit()
    logger.info("Retention sweep complete: %d pruned, %d errors", results["pruned"], results["errors"])
    return results
