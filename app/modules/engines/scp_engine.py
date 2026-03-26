import asyncio
import logging
import tempfile
import paramiko

from app.modules.engines.base import BackupEngine
from app.models.device import Device
from app.models.credential import Credential

logger = logging.getLogger(__name__)


class SCPEngine(BackupEngine):
    """SCP-based backup engine using Paramiko for direct file pull."""

    def _scp_fetch(self, device: Device, credential: Credential) -> str:
        host = device.ip_address
        port = device.port or 22
        username = credential.username
        password = credential.get_password()

        transport = paramiko.Transport((host, port))
        try:
            # Handle legacy SSH crypto for older FastIron firmware
            try:
                sec_opts = transport.get_security_options()
                sec_opts.kex = [
                    "diffie-hellman-group14-sha256",
                    "diffie-hellman-group14-sha1",
                    "diffie-hellman-group1-sha1",
                ]
            except Exception:
                pass  # Use defaults if setting kex fails

            transport.connect(username=username, password=password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            try:
                with tempfile.NamedTemporaryFile(suffix=".cfg", delete=True) as tmp:
                    # FastIron exposes runConfig and startConfig as SCP-pullable files
                    sftp.get("runConfig", tmp.name)
                    tmp.seek(0)
                    config_text = tmp.read().decode("utf-8", errors="replace")
                return config_text
            finally:
                sftp.close()
        finally:
            transport.close()

    def _scp_test(self, device: Device, credential: Credential) -> bool:
        host = device.ip_address
        port = device.port or 22
        username = credential.username
        password = credential.get_password()

        transport = paramiko.Transport((host, port))
        try:
            try:
                sec_opts = transport.get_security_options()
                sec_opts.kex = [
                    "diffie-hellman-group14-sha256",
                    "diffie-hellman-group14-sha1",
                    "diffie-hellman-group1-sha1",
                ]
            except Exception:
                pass
            transport.connect(username=username, password=password)
        finally:
            transport.close()
        return True

    async def fetch_config(self, device: Device, credential: Credential) -> str:
        logger.info("SCP: fetching runConfig from %s (%s)", device.hostname, device.ip_address)
        try:
            config = await asyncio.to_thread(self._scp_fetch, device, credential)
            logger.info("SCP: successfully fetched config from %s (%d bytes)", device.hostname, len(config))
            return config
        except paramiko.AuthenticationException:
            raise PermissionError(f"SCP auth failed for {device.hostname} ({device.ip_address})")
        except Exception as e:
            raise RuntimeError(f"SCP error on {device.hostname}: {e}")

    async def test_connection(self, device: Device, credential: Credential) -> bool:
        logger.info("SCP: testing connection to %s (%s)", device.hostname, device.ip_address)
        try:
            return await asyncio.to_thread(self._scp_test, device, credential)
        except Exception as e:
            logger.warning("SCP: connection test failed for %s: %s", device.hostname, e)
            return False
