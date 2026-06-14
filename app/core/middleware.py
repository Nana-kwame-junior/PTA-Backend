"""Rate limiting and security middleware."""

import hashlib
import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            bucket = [t for t in self._hits[key] if now - t < window_seconds]
            if len(bucket) >= limit:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            return True


_rate_limiter = InMemoryRateLimiter()

STRICT_PATHS = {
    "/api/v1/auth/web/login": (10, 60),
    "/api/v1/auth/web/forgot-password": (5, 60),
    "/api/v1/auth/web/reset-password": (5, 60),
    "/api/v1/auth/parent/request-otp": (5, 60),
    "/api/v1/auth/parent/verify-otp": (10, 60),
}
DEFAULT_LIMIT = (120, 60)
GLOBAL_LIMIT = (300, 60)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        key_base = _client_key(request)
        path = request.url.path

        if not _rate_limiter.allow(f"global:{key_base}", *GLOBAL_LIMIT):
            return JSONResponse(
                status_code=429,
                content={"success": False, "detail": "Too many requests. Please slow down."},
            )

        limit_rule = DEFAULT_LIMIT
        for prefix, rule in STRICT_PATHS.items():
            if path.startswith(prefix):
                limit_rule = rule
                break

        if not _rate_limiter.allow(f"{path}:{key_base}", *limit_rule):
            return JSONResponse(
                status_code=429,
                content={"success": False, "detail": "Rate limit exceeded. Try again shortly."},
            )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def hash_reset_token(token: str) -> str:
    pepper = settings.jwt_secret or "pta-reset-pepper"
    return hashlib.sha256(f"{pepper}:{token}".encode()).hexdigest()
