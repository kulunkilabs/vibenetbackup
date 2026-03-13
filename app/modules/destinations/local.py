import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.destinations.base import DestinationBackend
from app.config import get_settings

logger = logging.getLogger(__name__)


class LocalDestination(DestinationBackend):
    """Save text config backups to the local filesystem as .cfg files."""

    async def save(self, hostname: str, config_text: str, config: dict[str, Any]) -> str:
        base_dir = config.get("path", get_settings().BACKUP_DIR)
        device_dir = os.path.join(base_dir, hostname)
        os.makedirs(device_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}.cfg"
        filepath = os.path.join(device_dir, filename)

        await asyncio.to_thread(self._write_file, filepath, config_text)

        latest = os.path.join(device_dir, "latest.cfg")
        if os.path.islink(latest):
            os.unlink(latest)
        try:
            os.symlink(filepath, latest)
        except OSError:
            pass

        logger.info("Local: saved backup to %s (%d bytes)", filepath, len(config_text))
        return filepath

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def delete(self, path: str, config: dict[str, Any]) -> None:
        if os.path.exists(path):
            await asyncio.to_thread(os.remove, path)
            logger.info("Local: deleted backup at %s", path)
