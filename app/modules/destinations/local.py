import gzip
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
        compress = config.get("compress", False)
        safe_hostname = os.path.basename(hostname.replace("\\", "/")) or "unknown"
        device_dir = os.path.join(base_dir, safe_hostname)
        os.makedirs(device_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")

        if compress:
            filename = f"{timestamp}.cfg.gz"
            filepath = os.path.join(device_dir, filename)
            await asyncio.to_thread(self._write_compressed, filepath, config_text)
            latest_name = "latest.cfg.gz"
        else:
            filename = f"{timestamp}.cfg"
            filepath = os.path.join(device_dir, filename)
            await asyncio.to_thread(self._write_file, filepath, config_text)
            latest_name = "latest.cfg"

        latest = os.path.join(device_dir, latest_name)
        if os.path.islink(latest):
            os.unlink(latest)
        try:
            os.symlink(filepath, latest)
        except OSError:
            pass

        logger.info("Local: saved backup to %s (%d bytes)", filepath, len(config_text))
        return filepath

    async def save_binary(
        self,
        hostname: str,
        data: bytes,
        extension: str,
        config: dict[str, Any],
    ) -> str:
        base_dir = config.get("path", get_settings().BACKUP_DIR)
        safe_hostname = os.path.basename(hostname.replace("\\", "/")) or "unknown"
        device_dir = os.path.join(base_dir, safe_hostname)
        # Path-traversal guard: hostname must not escape base_dir.
        if not os.path.realpath(device_dir).startswith(os.path.realpath(base_dir)):
            raise ValueError(f"Invalid hostname for path: {hostname}")
        os.makedirs(device_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join(device_dir, f"{timestamp}{extension}")
        await asyncio.to_thread(self._write_binary, filepath, data)

        latest = os.path.join(device_dir, f"latest{extension}")
        if os.path.islink(latest):
            os.unlink(latest)
        try:
            os.symlink(filepath, latest)
        except OSError:
            pass

        logger.info("Local: saved binary backup to %s (%d bytes)", filepath, len(data))
        return filepath

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _write_compressed(path: str, content: str) -> None:
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _write_binary(path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)

    async def delete(self, path: str, config: dict[str, Any]) -> None:
        if os.path.exists(path):
            await asyncio.to_thread(os.remove, path)
            logger.info("Local: deleted backup at %s", path)
