"""Shared rate limiter (slowapi) for abuse protection on public endpoints.

Keyed on the real client IP. Behind Replit's proxy the client address arrives
in the X-Forwarded-For header, so we read the left-most entry there before
falling back to the socket peer address.

Limits are in-memory (per process). The backend runs as a single uvicorn
worker, so this is sufficient for coarse IP throttling. Per-account
brute-force protection (login lockout, reset throttling) is enforced in the
database so it holds across restarts and instances.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from slowapi.errors import RateLimitExceeded


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Friendly 429 — never leak the internal limit string to users."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests — please slow down and try again in a minute."},
    )
"""Shared rate limiter (slowapi) for abuse protection on public endpoints.

Keyed on the real client IP. Behind Replit's proxy the client address arrives
in the X-Forwarded-For header, so we read the left-most entry there before
falling back to the socket peer address.

Limits are in-memory (per process). The backend runs as a single uvicorn
worker, so this is sufficient for coarse IP throttling. Per-account
brute-force protection (login lockout, reset throttling) is enforced in the
database so it holds across restarts and instances.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from slowapi.errors import RateLimitExceeded


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Friendly 429 — never leak the internal limit string to users."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests — please slow down and try again in a minute."},
    )
