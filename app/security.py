"""Security utilities for VIBENetBackup."""
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

security = HTTPBasic(auto_error=False)

_COOKIE_NAME = "vibenet_session"
_SESSION_TTL = 14 * 24 * 3600  # 14 days in seconds


def _sign(payload: str) -> str:
    key = get_settings().SECRET_KEY.encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def generate_session_token() -> str:
    expiry = int(time.time()) + _SESSION_TTL
    nonce = secrets.token_hex(16)
    payload = f"{expiry}:{nonce}"
    return f"{payload}:{_sign(payload)}"


def verify_session_token(token: str) -> bool:
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        expiry, nonce, sig = parts
        payload = f"{expiry}:{nonce}"
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        return int(expiry) > int(time.time())
    except Exception:
        return False


def verify_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    expected_username = getattr(settings, "AUTH_USERNAME", "admin")
    expected_password = getattr(settings, "AUTH_PASSWORD", "admin")
    return (
        secrets.compare_digest(username, expected_username)
        and secrets.compare_digest(password, expected_password)
    )


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
):
    if request.url.path in ("/health", "/login"):
        return True

    # Valid session cookie
    token = request.cookies.get(_COOKIE_NAME)
    if token and verify_session_token(token):
        return True

    # HTTP Basic fallback (API / curl)
    if credentials and verify_credentials(credentials.username, credentials.password):
        return True

    # API paths get 401
    if request.url.path.startswith("/api/"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Browser — redirect to login
    return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
