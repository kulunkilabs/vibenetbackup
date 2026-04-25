import asyncio
import logging
import paramiko
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

from app.modules.engines.base import BackupEngine
from app.modules.engines.ssh_auth import client_connect_kwargs
from app.models.device import Device, get_config_commands, get_netmiko_device_type
from app.models.credential import Credential

logger = logging.getLogger(__name__)


class NetmikoEngine(BackupEngine):
    """SSH-based backup engine using Netmiko."""

    # Device types that need slower timing for prompt detection
    SLOW_PROMPT_TYPES = {"nokia_sros", "nokia_sros_md"}

    def _build_params(self, device: Device, credential: Credential) -> dict:
        if not credential.username:
            raise ValueError(f"Credential '{credential.name}' has no username — SSH requires a username")
        # Map our device_type to Netmiko's device_type (e.g., opnsense -> linux)
        netmiko_device_type = get_netmiko_device_type(device.device_type)
        params = {
            "device_type": netmiko_device_type,
            "host": device.ip_address,
            "port": device.port or 22,
            "username": credential.username,
            "password": credential.get_password(),
            "timeout": 30,
            "conn_timeout": 30,
            "banner_timeout": 30,
        }
        # Nokia SR OS devices need extra time for prompt detection
        if device.device_type in self.SLOW_PROMPT_TYPES:
            params["global_delay_factor"] = 2
            params["banner_timeout"] = 60
        secret = credential.get_enable_secret()
        if secret:
            params["secret"] = secret
        if credential.ssh_key_path:
            params["use_keys"] = True
            params["key_file"] = credential.ssh_key_path
        return params

    def _open_proxy(self, device: Device, credential: Credential) -> tuple:
        """Open a direct-tcpip channel through the jump host. Returns (jump_client, channel).
        Uses proxy_credential if set, otherwise falls back to the device credential."""
        proxy_cred = device.proxy_credential or credential
        logger.info(
            "Netmiko: opening proxy jump %s:%d → %s:%d (proxy user: %s)",
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

    def _connect_and_fetch(self, device: Device, credential: Credential, params: dict, commands: list[str]) -> str:
        jump = None
        try:
            if device.proxy_host:
                jump, sock = self._open_proxy(device, credential)
                params = {**params, "sock": sock}
            conn = ConnectHandler(**params)
            try:
                if "secret" in params:
                    conn.enable()
                parts = []
                for cmd in commands:
                    output = conn.send_command(cmd, read_timeout=120)
                    parts.append(output)
                return "\n".join(parts)
            finally:
                conn.disconnect()
        finally:
            if jump:
                jump.close()

    def _connect_and_test(self, device: Device, credential: Credential, params: dict) -> bool:
        jump = None
        try:
            if device.proxy_host:
                jump, sock = self._open_proxy(device, credential)
                params = {**params, "sock": sock}
            conn = ConnectHandler(**params)
            try:
                prompt = conn.find_prompt()
                return bool(prompt)
            except Exception:
                # find_prompt() can fail on devices with unusual prompts (e.g. Nokia SAR)
                # If ConnectHandler succeeded, the connection itself is valid
                logger.debug("find_prompt() failed, but connection was established")
                return True
            finally:
                conn.disconnect()
        finally:
            if jump:
                jump.close()

    async def fetch_config(self, device: Device, credential: Credential) -> str:
        params = self._build_params(device, credential)
        commands = get_config_commands(device.device_type)
        logger.info(
            "Netmiko: fetching config from %s (%s) type=%s (netmiko: %s) cmds=%s",
            device.hostname, device.ip_address, device.device_type, 
            params["device_type"], commands,
        )
        try:
            output = await asyncio.to_thread(self._connect_and_fetch, device, credential, params, commands)
            logger.info("Netmiko: successfully fetched config from %s (%d bytes)", device.hostname, len(output))
            return output
        except NetmikoTimeoutException:
            raise ConnectionError(f"Timeout connecting to {device.hostname} ({device.ip_address})")
        except NetmikoAuthenticationException:
            raise PermissionError(f"Authentication failed for {device.hostname} ({device.ip_address})")
        except Exception as e:
            raise RuntimeError(f"Netmiko error on {device.hostname}: {e}")

    async def test_connection(self, device: Device, credential: Credential) -> bool:
        params = self._build_params(device, credential)
        logger.info("Netmiko: testing connection to %s (%s)", device.hostname, device.ip_address)
        try:
            return await asyncio.to_thread(self._connect_and_test, device, credential, params)
        except Exception as e:
            logger.warning("Netmiko: connection test failed for %s: %s", device.hostname, e)
            return False
