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
        if not credential.username:
            raise ValueError(f"Credential '{credential.name}' has no username — pfSense requires a username")
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

        # Fallback: session-based PHP endpoint (no package needed)
        logger.info("pfSense: trying PHP endpoint for %s", device.hostname)

        # Step 1: GET login page to obtain CSRF token
        resp = await self._try_request(
            client, device, "GET", "/index.php", timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"pfSense login page returned HTTP {resp.status_code} for {device.hostname}"
            )
        actual_base = str(resp.url).rsplit("/", 1)[0]
        csrf_token = self._extract_csrf_token(resp.text)
        logger.debug("pfSense: login CSRF token extracted (%s)", "found" if csrf_token else "MISSING")

        # Headers required by pfSense CSRF origin checking
        csrf_headers = {
            "Referer": f"{actual_base}/index.php",
            "Origin": actual_base,
        }

        # Step 2: POST login credentials to establish session cookie
        login_data = {
            "__csrf_magic": csrf_token,
            "usernamefld": username,
            "passwordfld": password,
            "login": "Sign In",
        }
        resp = await client.post(
            f"{actual_base}/index.php",
            data=login_data,
            headers=csrf_headers,
            timeout=30,
        )
        logger.debug(
            "pfSense: login POST status=%d, url=%s, cookies=%s",
            resp.status_code, resp.url, list(client.cookies.keys()),
        )
        # 403 on login POST = CSRF rejection (missing/bad token or origin check)
        if resp.status_code == 403:
            raise RuntimeError(
                f"pfSense CSRF validation failed for {device.hostname} — "
                f"login POST returned 403 (token {'present' if csrf_token else 'MISSING'})"
            )
        # pfSense redirects to / on success; check we're not still on the login page
        if "usernamefld" in resp.text and "passwordfld" in resp.text:
            # Distinguish CSRF failure from bad credentials
            if not csrf_token:
                raise RuntimeError(
                    f"pfSense login failed for {device.hostname} — "
                    "could not extract CSRF token from login page"
                )
            raise PermissionError(
                f"pfSense authentication failed for {device.hostname} — "
                "check web UI username and password"
            )

        # Step 3: GET backup page with session cookie to get a new CSRF token
        resp = await client.get(
            f"{actual_base}/diag_backup.php", timeout=30,
        )
        self._check_pfsense_status(resp, device, "backup page")
        csrf_token = self._extract_csrf_token(resp.text)
        if not csrf_token:
            raise RuntimeError(
                f"pfSense: could not extract CSRF token from backup page for {device.hostname}"
            )

        # Step 4: POST to download the config XML
        post_data = {
            "__csrf_magic": csrf_token,
            "backuparea": "",
            "nopackages": "",
            "donotbackuprrd": "",
            "download": "Download configuration as XML",
        }
        backup_headers = {
            "Referer": f"{actual_base}/diag_backup.php",
            "Origin": actual_base,
        }
        resp = await client.post(
            f"{actual_base}/diag_backup.php",
            data=post_data,
            headers=backup_headers,
            timeout=60,
        )

        if resp.status_code == 200 and "<?xml" in resp.text[:100]:
            logger.info(
                "pfSense: got config via PHP endpoint for %s (%d bytes)",
                device.hostname, len(resp.text),
            )
            return resp.text
        if resp.status_code == 200:
            # Got 200 but not XML — likely session expired or wrong page
            raise RuntimeError(
                f"pfSense backup page did not return XML for {device.hostname} — "
                "check user has 'WebCfg - Diagnostics: Backup & Restore' privilege"
            )
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
        """Extract CSRF token from pfSense HTML page.

        pfSense uses csrf-magic which can inject the token as:
        1. A hidden input: <input name="__csrf_magic" value="sid:..." />
        2. A JS variable: var csrfMagicToken = "sid:...";
        """
        # Hidden input field (most common)
        match = re.search(r'name="__csrf_magic"\s+value="([^"]+)"', html)
        if match:
            return match.group(1)
        # Reversed attribute order
        match = re.search(r'value="([^"]+)"\s+name="__csrf_magic"', html)
        if match:
            return match.group(1)
        # Single-quoted variant
        match = re.search(r"name='__csrf_magic'\s+value='([^']+)'", html)
        if match:
            return match.group(1)
        # JavaScript injection (csrf-magic.js rewrite mode)
        match = re.search(r'var\s+csrfMagicToken\s*=\s*["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        logger.warning("pfSense: could not extract CSRF token from page")
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

                    # Fall back to session-based PHP login
                    username = credential.username
                    password = credential.get_password()

                    # GET login page for CSRF token
                    resp = await self._try_request(
                        client, device, "GET", "/index.php", timeout=10,
                    )
                    if resp.status_code >= 400:
                        raise RuntimeError(f"pfSense login page returned HTTP {resp.status_code}")
                    actual_base = str(resp.url).rsplit("/", 1)[0]
                    csrf_token = self._extract_csrf_token(resp.text)

                    # POST login
                    csrf_headers = {
                        "Referer": f"{actual_base}/index.php",
                        "Origin": actual_base,
                    }
                    login_data = {
                        "__csrf_magic": csrf_token,
                        "usernamefld": username,
                        "passwordfld": password,
                        "login": "Sign In",
                    }
                    resp = await client.post(
                        f"{actual_base}/index.php", data=login_data,
                        headers=csrf_headers, timeout=10,
                    )
                    if resp.status_code == 403:
                        raise RuntimeError(
                            f"pfSense CSRF validation failed for {device.hostname} — "
                            "login POST returned 403"
                        )
                    if "usernamefld" in resp.text and "passwordfld" in resp.text:
                        raise PermissionError(
                            f"pfSense authentication failed for {device.hostname} — "
                            "check web UI username and password"
                        )

                    # Verify we can reach the backup page
                    resp = await client.get(
                        f"{actual_base}/diag_backup.php", timeout=10,
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
