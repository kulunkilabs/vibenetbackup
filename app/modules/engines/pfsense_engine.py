import logging
import json
import re
import ssl
import httpx

from app.modules.engines.base import BackupEngine
from app.models.device import Device
from app.models.credential import Credential

logger = logging.getLogger(__name__)


class PfSenseEngine(BackupEngine):
    """
    Backup engine for pfSense and OPNsense firewalls.

    Supports both:
    - pfSense: Uses /api/v1/ (requires pfSense-REST-API package) or /diag_backup.php
    - OPNsense: Uses /api/core/backup/ endpoint

    Features:
    - Custom port support via device.port (defaults to 443)
    - HTTPS first with automatic HTTP fallback
    - Self-signed certificate handling
    """

    def __init__(self, api_type: str = "auto"):
        """
        Args:
            api_type: "pfsense", "opnsense", or "auto" (auto-detect based on device_type)
        """
        self.api_type = api_type

    def _detect_api_type(self, device: Device) -> str:
        """Auto-detect firewall type from device_type."""
        dt = device.device_type.lower()
        if "pfsense" in dt:
            return "pfsense"
        elif "opnsense" in dt or "opensense" in dt:
            return "opnsense"
        return "pfsense"  # default

    def _build_base_url(self, device: Device, scheme: str = "https") -> str:
        """Build base URL with custom port support."""
        port = device.port or 443
        # Only include port in URL if non-standard
        if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
            return f"{scheme}://{device.ip_address}"
        return f"{scheme}://{device.ip_address}:{port}"

    async def _try_request(
        self,
        client: httpx.AsyncClient,
        device: Device,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Try HTTPS first, fall back to HTTP if connection fails."""
        timeout = kwargs.pop("timeout", 60)

        # Try HTTPS first
        https_url = f"{self._build_base_url(device, 'https')}{path}"
        try:
            logger.debug("Trying HTTPS: %s %s", method, https_url)
            resp = await client.request(method, https_url, timeout=timeout, **kwargs)
            return resp
        except (httpx.ConnectError, httpx.ConnectTimeout, ssl.SSLError) as e:
            logger.debug("HTTPS failed for %s (%s), trying HTTP fallback", device.hostname, e)

        # Fall back to HTTP
        http_url = f"{self._build_base_url(device, 'http')}{path}"
        logger.info("Falling back to HTTP: %s %s", method, http_url)
        resp = await client.request(method, http_url, timeout=timeout, **kwargs)
        return resp

    def _check_pfsense_status(self, resp: httpx.Response, device: Device, context: str) -> None:
        """Raise descriptive errors for pfSense HTTP error codes."""
        if resp.status_code == 401:
            raise PermissionError(
                f"pfSense authentication failed for {device.hostname} — "
                "check web UI username/password, or API credentials if using "
                "the pfSense REST API package"
            )
        if resp.status_code == 403:
            raise PermissionError(
                f"pfSense access denied for {device.hostname} — "
                "the user lacks the required privilege. "
                "Ensure the user has 'WebCfg - Diagnostics: Backup & Restore' privilege "
                "(or admin role) in User Manager > Edit User > Effective Privileges"
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"pfSense {context} failed for {device.hostname}: HTTP {resp.status_code}"
            )

    async def _fetch_pfsense_config(
        self,
        device: Device,
        credential: Credential,
        client: httpx.AsyncClient,
    ) -> str:
        """Fetch config from pfSense via REST API or PHP endpoint."""
        username = credential.username
        password = credential.get_password()

        # Try REST API v1 first (requires pfSense-REST-API package)
        logger.info("pfSense: trying REST API for %s", device.hostname)

        try:
            resp = await self._try_request(
                client, device, "GET", "/api/v1/config/backup",
                auth=(username, password), timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data:
                    logger.info("pfSense: got config via REST API for %s", device.hostname)
                    return data["data"]
                return resp.text
            if resp.status_code in (401, 403):
                self._check_pfsense_status(resp, device, "REST API")
        except (PermissionError, RuntimeError):
            raise
        except (httpx.HTTPError, json.JSONDecodeError):
            logger.debug("pfSense: REST API failed, falling back to PHP endpoint")

        # Fallback: Use the backup PHP endpoint
        logger.info("pfSense: trying PHP endpoint for %s", device.hostname)

        # First GET to get the CSRF token
        resp = await self._try_request(
            client, device, "GET", "/diag_backup.php",
            auth=(username, password), timeout=30,
        )
        self._check_pfsense_status(resp, device, "backup page")

        # Detect which scheme succeeded for the follow-up POST
        actual_base = str(resp.url).split("/diag_backup.php")[0]

        csrf_token = self._extract_csrf_token(resp.text)

        # POST to download the config
        post_data = {
            "__csrf_magic": csrf_token,
            "backuparea": "",
            "nopackages": "",
            "donotbackuprrd": "",
            "download": "Download configuration as XML",
        }

        resp = await client.post(
            f"{actual_base}/diag_backup.php",
            data=post_data,
            auth=(username, password),
            timeout=60,
        )

        if resp.status_code == 200:
            logger.info(
                "pfSense: got config via PHP endpoint for %s (%d bytes)",
                device.hostname, len(resp.text),
            )
            return resp.text
        self._check_pfsense_status(resp, device, "backup download")

    async def _fetch_opnsense_config(
        self,
        device: Device,
        credential: Credential,
        client: httpx.AsyncClient,
    ) -> str:
        """Fetch config from OPNsense via API."""
        username = credential.username
        password = credential.get_password()

        logger.info("OPNsense: fetching config from %s", device.hostname)

        resp = await self._try_request(
            client, device, "GET", "/api/core/backup/download/this",
            auth=(username, password), timeout=60,
        )

        if resp.status_code == 200:
            logger.info(
                "OPNsense: got config for %s (%d bytes)",
                device.hostname, len(resp.text),
            )
            return resp.text
        elif resp.status_code == 401:
            raise PermissionError(
                f"OPNsense authentication failed for {device.hostname} — "
                "use API key as username and API secret as password "
                "(System > Access > Users > API keys)"
            )
        elif resp.status_code == 403:
            raise PermissionError(
                f"OPNsense access denied for {device.hostname} — "
                "the API key works but the user lacks the required privilege. "
                "Add 'Diagnostics: Configuration History' to the user or group "
                "(System > Access > Users > Edit user > Effective Privileges)"
            )
        else:
            raise RuntimeError(f"OPNsense API returned {resp.status_code}: {resp.text[:200]}")

    def _extract_csrf_token(self, html: str) -> str:
        """Extract CSRF token from pfSense HTML page."""
        match = re.search(r'name="__csrf_magic" value="([^"]+)"', html)
        if match:
            return match.group(1)
        # Try alternative format
        match = re.search(r'__csrf_magic\s*value=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        return ""

    async def fetch_config(self, device: Device, credential: Credential) -> str:
        api_type = self._detect_api_type(device) if self.api_type == "auto" else self.api_type

        # Create client with SSL verification disabled (common for self-signed certs)
        # follow_redirects needed for some pfSense setups that redirect HTTP->HTTPS
        async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
            try:
                if api_type == "opnsense":
                    return await self._fetch_opnsense_config(device, credential, client)
                else:
                    return await self._fetch_pfsense_config(device, credential, client)
            except (PermissionError, RuntimeError):
                raise
            except httpx.ConnectError as e:
                raise ConnectionError(
                    f"Cannot connect to {device.hostname} ({device.ip_address}:{device.port or 443}): {e}"
                )
            except httpx.ConnectTimeout:
                raise ConnectionError(
                    f"Connection timeout to {device.hostname} ({device.ip_address}:{device.port or 443})"
                )
            except Exception as e:
                raise RuntimeError(f"{api_type} backup error on {device.hostname}: {e}")

    async def test_connection(self, device: Device, credential: Credential) -> bool:
        """Test connectivity and authentication against the firewall API."""
        api_type = self._detect_api_type(device) if self.api_type == "auto" else self.api_type

        async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
            try:
                if api_type == "opnsense":
                    # Use the actual backup endpoint to verify both connectivity and auth
                    resp = await self._try_request(
                        client, device, "GET", "/api/core/backup/download/this",
                        auth=(credential.username, credential.get_password()),
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        return True
                    if resp.status_code == 401:
                        raise PermissionError(
                            "Authentication failed — OPNsense API requires an API key (username) "
                            "and API secret (password), not web UI credentials"
                        )
                    if resp.status_code == 403:
                        raise PermissionError(
                            "Access denied — API key is valid but the user lacks the "
                            "'Diagnostics: Configuration History' privilege "
                            "(System > Access > Users > Edit user > Effective Privileges)"
                        )
                    raise RuntimeError(f"OPNsense API returned HTTP {resp.status_code}")
                else:
                    # pfSense: try REST API first, then PHP backup page
                    auth = (credential.username, credential.get_password())

                    # Try REST API (if installed)
                    try:
                        resp = await self._try_request(
                            client, device, "GET", "/api/v1/config/backup",
                            auth=auth, timeout=10,
                        )
                        if resp.status_code == 200:
                            return True
                        if resp.status_code in (401, 403):
                            self._check_pfsense_status(resp, device, "REST API")
                    except (PermissionError, RuntimeError):
                        raise
                    except (httpx.HTTPError, json.JSONDecodeError):
                        pass  # REST API not installed, try PHP endpoint

                    # Fall back to PHP backup page
                    resp = await self._try_request(
                        client, device, "GET", "/diag_backup.php",
                        auth=auth, timeout=10,
                    )
                    if resp.status_code == 200:
                        return True
                    self._check_pfsense_status(resp, device, "backup page")
            except (PermissionError, RuntimeError):
                raise
            except Exception as e:
                logger.warning(
                    "%s: connection test failed for %s: %s",
                    api_type, device.hostname, e,
                )
                return False
