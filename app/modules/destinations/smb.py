import asyncio
import gzip
import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.destinations.base import DestinationBackend

logger = logging.getLogger(__name__)


class SMBDestination(DestinationBackend):
    """Push backups to an SMB/CIFS network share."""

    async def save(self, hostname: str, config_text: str, config: dict[str, Any]) -> str:
        server = config["server"]
        share = config["share"]
        username = config.get("username", "")
        password = config.get("password", "")
        base_path = config.get("base_path", "backups")
        compress = config.get("compress", False)

        safe_hostname = hostname.replace("\\", "/").split("/")[-1] or "unknown"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        remote_dir = f"{base_path}/{safe_hostname}"
        ext = ".cfg.gz" if compress else ".cfg"
        remote_path = f"{remote_dir}/{timestamp}{ext}"

        def _smb_write():
            import os
            import smbclient
            smbclient.register_session(server, username=username, password=password)

            unc_dir = f"\\\\{server}\\{share}\\{remote_dir.replace('/', os.sep)}"
            unc_path = f"\\\\{server}\\{share}\\{remote_path.replace('/', os.sep)}"

            # Ensure directory exists
            try:
                smbclient.makedirs(unc_dir)
            except OSError:
                pass  # Directory may already exist

            if compress:
                data = gzip.compress(config_text.encode("utf-8"))
                with smbclient.open_file(unc_path, mode="wb") as f:
                    f.write(data)
            else:
                with smbclient.open_file(unc_path, mode="w", encoding="utf-8") as f:
                    f.write(config_text)

            return unc_path

        path = await asyncio.to_thread(_smb_write)
        logger.info("SMB: saved backup to %s", path)
        return path

    async def delete(self, path: str, config: dict[str, Any]) -> None:
        server = config["server"]
        username = config.get("username", "")
        password = config.get("password", "")

        def _smb_delete():
            import smbclient
            smbclient.register_session(server, username=username, password=password)
            smbclient.remove(path)

        try:
            await asyncio.to_thread(_smb_delete)
            logger.info("SMB: deleted backup at %s", path)
        except Exception as e:
            logger.warning("SMB: failed to delete %s: %s", path, e)
