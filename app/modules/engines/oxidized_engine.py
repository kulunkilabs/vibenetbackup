import logging
from urllib.parse import urljoin
import httpx

from app.modules.engines.base import BackupEngine
from app.models.device import Device
from app.models.credential import Credential
from app.config import get_settings

logger = logging.getLogger(__name__)


class OxidizedEngine(BackupEngine):
    """Fetch configs from a running Oxidized instance via REST API."""

    def _base_url(self) -> str:
        return get_settings().OXIDIZED_URL.rstrip("/")

    async def fetch_config(self, device: Device, credential: Credential) -> str:
        base = self._base_url()
        url = f"{base}/node/fetch/{device.ip_address}"
        logger.info("Oxidized: fetching config for %s from %s", device.hostname, url)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                config = resp.text
                logger.info("Oxidized: got config for %s (%d bytes)", device.hostname, len(config))
                return config
            elif resp.status_code == 404:
                raise ValueError(f"Device {device.ip_address} not found in Oxidized")
            else:
                raise RuntimeError(f"Oxidized returned {resp.status_code}: {resp.text}")

    async def test_connection(self, device: Device, credential: Credential) -> bool:
        base = self._base_url()
        url = f"{base}/nodes.json"
        logger.info("Oxidized: testing connection to %s", url)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    nodes = resp.json()
                    # Check if our device is in the Oxidized node list
                    for node in nodes:
                        if node.get("ip") == device.ip_address or node.get("name") == device.hostname:
                            return True
                    logger.warning("Oxidized: device %s not found in node list", device.hostname)
                    return False
                return False
        except Exception as e:
            logger.warning("Oxidized: connection test failed: %s", e)
            return False
