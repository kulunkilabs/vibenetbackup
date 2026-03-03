"""Security utilities for VIBENetBackup."""
import secrets
import hashlib
from functools import wraps
from fastapi import HTTPException, Request, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.config import get_settings

security = HTTPBasic(auto_error=False)


def verify_credentials(credentials: HTTPBasicCredentials | None) -> bool:
    """Verify HTTP Basic Auth credentials."""
    if not credentials:
        return False
    
    settings = get_settings()
    expected_username = getattr(settings, 'AUTH_USERNAME', 'admin')
    expected_password = getattr(settings, 'AUTH_PASSWORD', 'admin')
    
    # Use constant-time comparison to prevent timing attacks
    is_username_correct = secrets.compare_digest(
        credentials.username, expected_username
    )
    is_password_correct = secrets.compare_digest(
        credentials.password, expected_password
    )
    
    return is_username_correct and is_password_correct


def require_auth(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    """Dependency to require authentication."""
    # Skip auth for health check (optional)
    if request.url.path == "/health":
        return True
    
    if not verify_credentials(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
