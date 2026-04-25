import asyncio
import logging
import tempfile
import paramiko

from app.modules.engines.base import BackupEngine
from app.modules.engines.ssh_auth import client_connect_kwargs, connect_transport
from app.models.device import Device
from app.models.credential import Credential

logger = logging.getLogger(__name__)


class SCPEngine(BackupEngine):
    """SCP-based backup engine using Paramiko for direct file pull."""

    def _open_proxy(self, device: Device, credential: Credential):
        """Open a direct-tcpip channel through the jump host. Returns (jump_client, channel).
        Uses proxy_credential if set, otherwise falls back to the device credential."""
        proxy_cred = device.proxy_credential or credential
        logger.info(
            "SCP: opening proxy jump %s:%d → %s:%d (proxy user: %s)",
            device.proxy_host, device.proxy_port or 22,
            device.ip_address, device.port or 22,
            proxy_cred.username,
        )
        jump = paramiko.SSHClient()
        jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump.connect(
            **client_connect_kwargs(
                device.proxy_host,
                device.proxy_port or 22,
                proxy_cred,
                "SSH proxy jump",
            )
        )
        channel = jump.get_transport().open_channel(
            "direct-tcpip",
            (device.ip_address, device.port or 22),
            ("", 0),
        )
        return jump, channel

    def _make_transport(self, device: Device, credential: Credential):
        """Create a Paramiko Transport, routing through a proxy jump host if configured."""
        if not credential.username:
            raise ValueError(f"Credential '{credential.name}' has no username — SSH/SCP requires a username")
        jump = None

        if device.proxy_host:
            jump, sock = self._open_proxy(device, credential)
            transport = paramiko.Transport(sock)
        else:
            transport = paramiko.Transport((device.ip_address, device.port or 22))

        try:
            sec_opts = transport.get_security_options()
            sec_opts.kex = [
                "diffie-hellman-group14-sha256",
                "diffie-hellman-group14-sha1",
                "diffie-hellman-group1-sha1",
            ]
        except Exception:
            pass

        connect_transport(transport, credential, "SSH/SCP")
        return jump, transport

    def _scp_fetch(self, device: Device, credential: Credential) -> str:
        jump, transport = self._make_transport(device, credential)
        try:
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
            if jump:
                jump.close()

    def _scp_test(self, device: Device, credential: Credential) -> bool:
        jump, transport = self._make_transport(device, credential)
        try:
            pass  # successful transport.connect() means auth passed
        finally:
            transport.close()
            if jump:
                jump.close()
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
