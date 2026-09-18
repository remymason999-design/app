"""Password reset router.

Two endpoints:
  POST /auth/forgot-password { email }  -> issues a 1-hour token and emails a
                                            reset link via Resend.
  POST /auth/reset-password  { token, new_password } -> rotates password.

Tokens are stored in `db.password_resets` and consumed on use. We always
return 200 from /forgot-password to prevent email enumeration. The token/link
is delivered ONLY by email (Resend); it is surfaced inline in the response
solely in development (never in a deployment) as a local convenience. The
endpoint is also IP rate limited to blunt abuse.
"""
import os
import logging
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from core import db, hash_password, logger
from email_service import send_password_reset_email
from rate_limit import limiter

logger = logging.getLogger("watchsmart.password_reset")

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_TTL_MIN = 60

# Per-account abuse throttle: cap how many reset tokens a single email can
# generate inside a short window so the endpoint can't be used to bombard a
# user's inbox (the IP rate limit below is the coarse first line of defence).
RESET_MAX_PER_WINDOW = 3
RESET_WINDOW_MIN = 15


def _is_dev() -> bool:
    """True only when positively running in the Replit dev environment.

    Fail-closed: a deployment, or any ambiguous/unknown environment, is treated
    as NON-dev so reset tokens are never surfaced in a response body.
    """
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return False
    return bool(os.environ.get("REPLIT_DEV_DOMAIN"))


def _frontend_origin(request: Request) -> str:
    """Resolve the absolute public origin for building email links.

    Priority:
      1. PUBLIC_APP_URL env (explicit, set for production).
      2. First http(s) origin in ALLOWED_ORIGINS.
      3. REPLIT_DEV_DOMAIN (development).
      4. The incoming request's base URL (frontend + API are same-origin).
    """
    explicit = os.environ.get("PUBLIC_APP_URL", "").strip()
    if explicit.startswith("http"):
        return explicit.rstrip("/")

    for o in [x.strip() for x in os.environ.get("ALLOWED_ORIGINS", "").split(",") if x.strip()]:
        if o.startswith("http"):
            return o.rstrip("/")

    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
    if dev_domain:
        return f"https://{dev_domain}"

    try:
        base = str(request.base_url).rstrip("/")
        if base.startswith("http"):
            return base
    except Exception:
        pass
    return ""


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=6)


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, payload: ForgotIn):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})

    # Always succeed to avoid email enumeration
    response = {"ok": True, "message": "If that email exists, a reset link has been issued."}

    if not user:
        return response

    now = datetime.now(timezone.utc)

    # Per-account abuse throttle — silently stop issuing more tokens once this
    # email has requested too many inside the window (response stays generic).
    window_start = (now - timedelta(minutes=RESET_WINDOW_MIN)).isoformat()
    recent = await db.password_resets.count_documents(
        {"email": email, "created_at": {"$gte": window_start}}
    )
    if recent >= RESET_MAX_PER_WINDOW:
        return response

    token = secrets.token_urlsafe(32)
    expires = now + timedelta(minutes=RESET_TTL_MIN)

    await db.password_resets.insert_one({
        "token": token,
        "user_id": user["user_id"],
        "email": email,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "used": False,
    })

    origin = _frontend_origin(request)
    reset_url = f"{origin}/reset-password?token={token}" if origin else f"/reset-password?token={token}"

    # Send email via Resend. Delivery result is logged only — never reflected in
    # the response body, so the response is byte-identical for existing and
    # non-existing emails (anti-enumeration).
    sent = await send_password_reset_email(email, reset_url, expires_in_min=RESET_TTL_MIN)
    if not sent:
        logger.error("Password reset email failed to send for a known user (email send returned False).")

    # DEV ONLY — surface the link inline so a developer can recover an account
    # locally without a real inbox. This is the sole branch that alters the
    # response shape, and it can never run in a deployment (_is_dev fails
    # closed), so the production contract stays uniform.
    if _is_dev():
        response.update({
            "reset_url": reset_url,
            "token": token,
            "expires_at": expires.isoformat(),
        })

    return response


@router.post("/reset-password")
@limiter.limit("10/minute")
async def reset_password(request: Request, payload: ResetIn):
    rec = await db.password_resets.find_one({"token": payload.token, "used": False})
    if not rec:
        raise HTTPException(400, "Invalid or already-used reset link")

    expires = rec.get("expires_at")
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and expires < datetime.now(timezone.utc):
        raise HTTPException(400, "Reset link has expired — request a new one")

    new_hash = hash_password(payload.new_password)
    # Bump password_changed_at so every existing token (any device) is invalidated.
    new_pw_ts = int(datetime.now(timezone.utc).timestamp()) + 1
    await db.users.update_one(
        {"user_id": rec["user_id"]},
        {"$set": {"password_hash": new_hash, "password_changed_at": new_pw_ts}},
    )
    # Drop any active sessions for this user.
    try:
        await db.user_sessions.delete_many({"user_id": rec["user_id"]})
    except Exception:
        pass
    await db.password_resets.update_one(
        {"token": payload.token},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "message": "Password updated. You can now sign in."}
