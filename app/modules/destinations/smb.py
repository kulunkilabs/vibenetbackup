import asyncio
import gzip
import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.destinations.base import DestinationBackend

logger = logging.getLogger(__name__)


class SMBDestination(DestinationBackend):
    """Push backups to an SMB/CIFS network share."""

    async def test(self, config: dict[str, Any]) -> dict:
        """Test SMB connectivity, authentication, and write permissions.

        Returns {"ok": bool, "steps": [{"step": str, "ok": bool, "msg": str}]}
        """
        server = config.get("server", "")
        share = config.get("share", "")
        username = config.get("username", "")
        password = config.get("password", "")
        base_path = config.get("base_path", "backups")

        steps: list[dict] = []

        def _run_test():
            import socket
            import smbclient

            # Step 1: TCP reachability (port 445)
            try:
                sock = socket.create_connection((server, 445), timeout=5)
                sock.close()
                steps.append({"step": "tcp", "ok": True, "msg": f"TCP port 445 reachable on {server}"})
            except Exception as e:
                steps.append({"step": "tcp", "ok": False, "msg": f"TCP port 445 unreachable on {server}: {e}"})
                return False

            # Step 2: Authentication
            try:
                smbclient.register_session(server, username=username, password=password)
                steps.append({"step": "auth", "ok": True, "msg": f"Authenticated as '{username or '(anonymous)'}'"})
            except Exception as e:
                steps.append({"step": "auth", "ok": False, "msg": f"Authentication failed: {e}"})
                return False

            # Step 3: List share root
            unc_share = f"\\\\{server}\\{share}"
            try:
                entries = list(smbclient.listdir(unc_share))
                steps.append({"step": "list", "ok": True, "msg": f"Share \\\\{server}\\{share} accessible ({len(entries)} entries in root)"})
            except Exception as e:
                steps.append({"step": "list", "ok": False, "msg": f"Cannot list share \\\\{server}\\{share}: {e}"})
                return False

            # Step 4: Write + delete test file in base_path
            unc_base = f"\\\\{server}\\{share}\\{base_path.replace('/', '\\')}"
            unc_test = f"{unc_base}\\.vibenetbackup_writetest"
            try:
                smbclient.makedirs(unc_base, exist_ok=True)
                with smbclient.open_file(unc_test, mode="w") as f:
                    f.write("vibenetbackup write test")
                smbclient.remove(unc_test)
                steps.append({"step": "write", "ok": True, "msg": f"Write/delete test passed in '{base_path}'"})
            except Exception as e:
                steps.append({"step": "write", "ok": False, "msg": f"Write permission check failed in '{base_path}': {e}"})
                return False

            return True

        try:
            ok = await asyncio.to_thread(_run_test)
        except Exception as e:
            steps.append({"step": "error", "ok": False, "msg": str(e)})
            ok = False

        for s in steps:
            if s["ok"]:
                logger.info("SMB test [%s] %s: %s", server, s["step"], s["msg"])
            else:
                logger.warning("SMB test [%s] %s: %s", server, s["step"], s["msg"])

        return {"ok": ok, "steps": steps}

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
            import smbclient
            smbclient.register_session(server, username=username, password=password)

            unc_dir = f"\\\\{server}\\{share}\\{remote_dir.replace('/', '\\')}"
            unc_path = f"\\\\{server}\\{share}\\{remote_path.replace('/', '\\')}"

            # Ensure directory exists
            smbclient.makedirs(unc_dir, exist_ok=True)

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
