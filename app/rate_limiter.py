"""Simple rate limiting for VIBENetBackup."""
import time
from functools import wraps
from fastapi import Request, HTTPException, status
from collections import defaultdict

# Simple in-memory rate limiter
# For production, consider using Redis
class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
    
    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        
        # Filter out old requests
        self.requests[key] = [t for t in self.requests[key] if t > window_start]
        
        if len(self.requests[key]) >= self.max_requests:
            return False
        
        self.requests[key].append(now)
        return True
    
    def get_retry_after(self, key: str) -> int:
        if not self.requests[key]:
            return 0
        oldest = min(self.requests[key])
        return max(0, int(self.window_seconds - (time.time() - oldest)))

# Global rate limiter instance
rate_limiter = RateLimiter(max_requests=60, window_seconds=60)


def rate_limit(requests_per_minute: int = 60):
    """Decorator to apply rate limiting to endpoints."""
    limiter = RateLimiter(max_requests=requests_per_minute, window_seconds=60)
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Try to find request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                for v in kwargs.values():
                    if isinstance(v, Request):
                        request = v
                        break
            
            if request:
                # Use client IP as key
                client_ip = request.client.host if request.client else request.headers.get("x-forwarded-for", "").split(",")[0].strip() or "unknown"
                if not limiter.is_allowed(client_ip):
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Rate limit exceeded",
                        headers={"Retry-After": str(limiter.get_retry_after(client_ip))}
                    )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def get_rate_limit_dependency(requests_per_minute: int = 60):
    """Dependency for rate limiting."""
    limiter = RateLimiter(max_requests=requests_per_minute, window_seconds=60)
    
    def check_rate_limit(request: Request):
        client_ip = request.client.host if request.client else request.headers.get("x-forwarded-for", "").split(",")[0].strip() or "unknown"
        if not limiter.is_allowed(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(limiter.get_retry_after(client_ip))}
            )
        return True
    
    return check_rate_limit
