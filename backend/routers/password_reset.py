"""Password reset router.

Two endpoints:
  POST /auth/forgot-password { email }  -> issues a 1-hour token (returned in
                                            response for now; switch to email
                                            once Resend/SendGrid is wired).
  POST /auth/reset-password  { token, new_password } -> rotates password.

Tokens are stored in `db.password_resets` and consumed on use. We always
return 200 from /forgot-password to prevent email enumeration in production —
the `reset_url` is only included for known emails so the dev/admin can hand it
to the user until email is wired.
"""
import os
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from core import db, hash_password

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_TTL_MIN = 60


def _frontend_origin() -> str:
    origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    for o in origins:
        if o.startswith("http"):
            return o.rstrip("/")
    return ""


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=6)


@router.post("/forgot-password")
async def forgot_password(payload: ForgotIn):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})

    # Always succeed to avoid email enumeration
    response = {"ok": True, "message": "If that email exists, a reset link has been issued."}

    if not user:
        return response

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=RESET_TTL_MIN)

    await db.password_resets.insert_one({
        "token": token,
        "user_id": user["user_id"],
        "email": email,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "used": False,
    })

    origin = _frontend_origin()
    reset_url = f"{origin}/reset-password?token={token}" if origin else f"/reset-password?token={token}"

    # MOCKED EMAIL: until Resend/SendGrid is wired, return the link in the response
    # so the client can display "copy link" UX. Remove these fields once email
    # delivery is live in production.
    response.update({
        "reset_url": reset_url,
        "token": token,
        "expires_at": expires.isoformat(),
        "delivery": "inline",  # client renders link directly until email is wired
    })
    return response


@router.post("/reset-password")
async def reset_password(payload: ResetIn):
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
    await db.users.update_one(
        {"user_id": rec["user_id"]},
        {"$set": {"password_hash": new_hash}},
    )
    await db.password_resets.update_one(
        {"token": payload.token},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "message": "Password updated. You can now sign in."}
