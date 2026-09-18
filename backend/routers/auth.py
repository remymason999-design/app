"""Auth router — email/password JWT + Google/Apple OAuth (standard OAuth 2.0)."""
import os
import base64
import json as _json
import uuid
import urllib.parse
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse

from core import (
    db, JWT_SECRET, JWT_ALGORITHM,
    RegisterIn, LoginIn, ChangePasswordIn,
    hash_password, verify_password,
    create_access_token, create_refresh_token, set_auth_cookies,
    clean_user, public_user, require_user,
    seed_notifications_for_user, httpx, logger,
)
import asyncio
from email_service import send_welcome_email
from rate_limit import limiter
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from push_notifications import (
    UserDeletionFenceBusy,
    UserNoLongerExists,
    create_user_notification,
    run_under_user_deletion_fence,
)

router = APIRouter(prefix="/auth", tags=["auth"])

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = f"{APPLE_ISSUER}/auth/keys"
APPLE_NATIVE_CLIENT_ID = os.environ.get("APPLE_NATIVE_CLIENT_ID", "com.watchsmart.app")
_apple_jwks_client = jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True, lifespan=3600)


class AppleAuthIn(BaseModel):
    identity_token: str
    authorization_code: str | None = None
    apple_user: str | None = None
    full_name: str | None = None
    email: str | None = None

# Brute-force protection (per-account, DB-backed so it survives restarts).
# After LOGIN_FAIL_THRESHOLD consecutive failures the account is locked for an
# exponentially increasing window, capped at LOGIN_LOCK_MAX_SEC.
LOGIN_FAIL_THRESHOLD = 5
LOGIN_LOCK_BASE_SEC = 60
LOGIN_LOCK_MAX_SEC = 30 * 60


def _fmt_wait(seconds: int) -> str:
    if seconds >= 60:
        mins = (seconds + 59) // 60
        return f"{mins} minute" + ("s" if mins != 1 else "")
    return f"{max(1, seconds)} second" + ("s" if seconds != 1 else "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _upsert_social_user(
    response: Response,
    *,
    email: str,
    name: str | None,
    picture: str | None,
    provider: str,
) -> dict:
    """Find or create a user from a social login, set auth cookies, return user+token."""
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "name": name or email.split("@")[0],
            "picture": picture,
            "auth_provider": provider,
            "subscriptions": [], "genres": [],
            "saved": [], "watched": [], "skipped": [],
            "excluded_categories": ["anime", "family", "bollywood"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user.copy())
        await seed_notifications_for_user(user["user_id"])
    else:
        update = {}
        if picture and not user.get("picture"):
            update["picture"] = picture
        if name and not user.get("name"):
            update["name"] = name
        if update:
            await db.users.update_one({"email": email}, {"$set": update})
            user.update(update)

    access = create_access_token(user["user_id"], email)
    refresh = create_refresh_token(user["user_id"])
    set_auth_cookies(response, access, refresh)
    return {"user": public_user(user), "access_token": access, "refresh_token": refresh}


def _decode_jwt_payload(token: str) -> dict:
    """Base64-decode the payload section of a JWT without verifying signature."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return _json.loads(base64.urlsafe_b64decode(part))
    except Exception as exc:
        raise HTTPException(401, "Invalid token payload") from exc


def _verify_apple_identity_token(identity_token: str) -> dict:
    """Verify an Apple identity token against Apple's public signing keys."""
    try:
        signing_key = _apple_jwks_client.get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APPLE_NATIVE_CLIENT_ID,
            issuer=APPLE_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Apple sign-in verification is temporarily unavailable") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Apple identity token is invalid or expired") from exc
    except Exception as exc:
        raise HTTPException(503, "Apple sign-in verification is temporarily unavailable") from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(401, "Apple identity token is missing a subject")
    return claims


def _apple_claim_email(claims: dict) -> str | None:
    email = claims.get("email")
    verified = claims.get("email_verified")
    if not isinstance(email, str) or verified not in (True, "true", "True", 1):
        return None
    return email.lower().strip()


def _apple_client_secret() -> str:
    team_id = os.environ.get("APPLE_TEAM_ID")
    key_id = os.environ.get("APPLE_KEY_ID")
    private_key = os.environ.get("APPLE_PRIVATE_KEY")
    if not team_id or not key_id or not private_key:
        raise HTTPException(
            503,
            "Apple sign-in is awaiting secure server configuration.",
        )
    private_key = private_key.strip()
    if (
        len(private_key) >= 2
        and private_key[0] == private_key[-1]
        and private_key[0] in {'"', "'"}
    ):
        private_key = private_key[1:-1].strip()
    private_key = private_key.replace("\\n", "\n").replace("\r\n", "\n")
    begin = "-----BEGIN PRIVATE KEY-----"
    end = "-----END PRIVATE KEY-----"
    if begin in private_key and end in private_key:
        body = private_key.split(begin, 1)[1].split(end, 1)[0]
        body = "".join(body.split())
        private_key = (
            f"{begin}\n"
            + "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
            + f"\n{end}\n"
        )
    elif private_key and all(
        char.isalnum() or char in "+/=" for char in private_key
    ):
        private_key = (
            f"{begin}\n"
            + "\n".join(
                private_key[i : i + 64] for i in range(0, len(private_key), 64)
            )
            + f"\n{end}\n"
        )
    now = datetime.now(timezone.utc)
    try:
        return jwt.encode(
            {
                "iss": team_id,
                "iat": now,
                "exp": now + timedelta(minutes=5),
                "aud": APPLE_ISSUER,
                "sub": APPLE_NATIVE_CLIENT_ID,
            },
            private_key,
            algorithm="ES256",
            headers={"kid": key_id},
        )
    except (TypeError, ValueError) as exc:
        logger.error("APPLE_PRIVATE_KEY is not a valid Sign in with Apple .p8 key")
        raise HTTPException(
            503,
            "Apple sign-in has an invalid server key configuration.",
        ) from exc


def _validated_apple_token_exchange(data: dict, expected_sub: str) -> str:
    exchange_identity_token = data.get("id_token")
    if not isinstance(exchange_identity_token, str) or not exchange_identity_token:
        raise HTTPException(401, "Apple authorization did not return an identity token")
    exchange_claims = _verify_apple_identity_token(exchange_identity_token)
    if exchange_claims.get("sub") != expected_sub:
        raise HTTPException(401, "Apple authorization identity did not match")
    refresh_token = data.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise HTTPException(503, "Apple did not return a revocable session. Please try again.")
    return refresh_token


async def _exchange_apple_authorization_code(code: str | None, expected_sub: str) -> str:
    if not code:
        raise HTTPException(400, "Apple did not return an authorization code. Please try again.")
    async with httpx.AsyncClient(timeout=10.0) as http:
        try:
            token_response = await http.post(
                f"{APPLE_ISSUER}/auth/token",
                data={
                    "client_id": APPLE_NATIVE_CLIENT_ID,
                    "client_secret": _apple_client_secret(),
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Apple sign-in is temporarily unavailable") from exc
    if token_response.status_code != 200:
        raise HTTPException(401, "Apple authorization could not be completed")
    return _validated_apple_token_exchange(token_response.json(), expected_sub)


async def _revoke_apple_refresh_token(refresh_token: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        try:
            revoke_response = await http.post(
                f"{APPLE_ISSUER}/auth/revoke",
                data={
                    "client_id": APPLE_NATIVE_CLIENT_ID,
                    "client_secret": _apple_client_secret(),
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                503,
                "Apple sign-in could not be disconnected. Please retry account deletion.",
            ) from exc
    if revoke_response.status_code != 200:
        raise HTTPException(
            503,
            "Apple sign-in could not be disconnected. Please retry account deletion.",
        )


# ---------------------------------------------------------------------------
# Email / password
# ---------------------------------------------------------------------------

@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, payload: RegisterIn, response: Response):
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": email,
        "name": payload.name.strip(),
        "password_hash": hash_password(payload.password),
        "picture": None,
        "auth_provider": "password",
        "subscriptions": [], "genres": [],
        "saved": [], "watched": [], "skipped": [],
        "excluded_categories": ["anime", "family", "bollywood"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.dob:
        doc["dob"] = payload.dob
    if payload.gender:
        doc["gender"] = payload.gender
    if payload.accept_terms:
        doc["terms_accepted_at"] = datetime.now(timezone.utc).isoformat()
        doc["privacy_accepted_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.insert_one(doc)
    await seed_notifications_for_user(user_id)
    # Welcome email — best-effort, never blocks signup.
    asyncio.create_task(send_welcome_email(email, payload.name.strip()))
    access = create_access_token(user_id, email)
    refresh = create_refresh_token(user_id)
    set_auth_cookies(response, access, refresh)
    return {"user": public_user(doc.copy()), "access_token": access, "refresh_token": refresh}


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    now = datetime.now(timezone.utc)

    # Brute-force lockout: if this account is currently locked, refuse early
    # (without revealing whether the password was correct).
    if user:
        lock_until = user.get("lockout_until")
        if lock_until:
            lu = datetime.fromisoformat(lock_until) if isinstance(lock_until, str) else lock_until
            if lu.tzinfo is None:
                lu = lu.replace(tzinfo=timezone.utc)
            if lu > now:
                wait = int((lu - now).total_seconds())
                raise HTTPException(429, f"Too many failed attempts. Try again in {_fmt_wait(wait)}.")

    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        # Count the failure against the account (only if it exists) and escalate
        # a lockout window once the threshold is crossed.
        if user:
            attempts = int(user.get("failed_login_attempts", 0)) + 1
            update = {"failed_login_attempts": attempts}
            if attempts >= LOGIN_FAIL_THRESHOLD:
                lock_sec = min(
                    LOGIN_LOCK_BASE_SEC * (2 ** (attempts - LOGIN_FAIL_THRESHOLD)),
                    LOGIN_LOCK_MAX_SEC,
                )
                update["lockout_until"] = (now + timedelta(seconds=lock_sec)).isoformat()
            await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
        raise HTTPException(401, "Invalid email or password")

    # Successful login — clear any failure counters / lockout.
    if user.get("failed_login_attempts") or user.get("lockout_until"):
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"failed_login_attempts": 0}, "$unset": {"lockout_until": ""}},
        )

    access = create_access_token(user["user_id"], email)
    refresh = create_refresh_token(user["user_id"])
    set_auth_cookies(response, access, refresh)
    return {"user": public_user(user), "access_token": access, "refresh_token": refresh}


@router.post("/apple")
@limiter.limit("10/minute")
async def native_apple_login(request: Request, payload: AppleAuthIn, response: Response):
    """Create or restore a WatchSmart session from a verified native Apple token."""
    claims = await asyncio.to_thread(_verify_apple_identity_token, payload.identity_token)
    apple_sub = claims["sub"].strip()

    user = await db.users.find_one({"apple_sub": apple_sub})
    if not user:
        email = _apple_claim_email(claims)
        if not email:
            raise HTTPException(
                400,
                "Apple did not provide a verified email address. Remove WatchSmart from "
                "Apple ID sign-in settings and try again.",
            )

        existing = await db.users.find_one({"email": email})
        if existing:
            # A concurrent request may have created this exact Apple identity
            # after the initial subject lookup.
            user = await db.users.find_one({"apple_sub": apple_sub})
        if existing and not user:
            raise HTTPException(
                409,
                "A WatchSmart account already uses this email. Sign in with your password "
                "below to securely link Sign in with Apple.",
            )

        if not user:
            apple_refresh_token = await _exchange_apple_authorization_code(
                payload.authorization_code,
                apple_sub,
            )
            display_name = (payload.full_name or "").strip()[:120]
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user = {
                "user_id": user_id,
                "email": email,
                "name": display_name or email.split("@")[0],
                "picture": None,
                "auth_provider": "apple",
                "apple_sub": apple_sub,
                "apple_refresh_token": apple_refresh_token,
                "subscriptions": [], "genres": [],
                "saved": [], "watched": [], "skipped": [],
                "excluded_categories": ["anime", "family", "bollywood"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            created = False
            try:
                await db.users.insert_one(user)
                created = True
            except DuplicateKeyError:
                # Another concurrent request may have created this Apple identity.
                user = await db.users.find_one({"apple_sub": apple_sub})
                if not user:
                    raise HTTPException(409, "This Apple account is already linked") from None
            if created:
                await seed_notifications_for_user(user_id)
    else:
        apple_refresh_token = await _exchange_apple_authorization_code(
            payload.authorization_code,
            apple_sub,
        )
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"apple_refresh_token": apple_refresh_token}},
        )
        user["apple_refresh_token"] = apple_refresh_token

    access = create_access_token(user["user_id"], user["email"])
    refresh = create_refresh_token(user["user_id"])
    set_auth_cookies(response, access, refresh)
    return {"user": public_user(user), "access_token": access, "refresh_token": refresh}


@router.post("/apple/link")
async def link_native_apple(
    payload: AppleAuthIn,
    request: Request,
    user: dict = Depends(require_user),
):
    """Link Apple only after the existing WatchSmart account authenticates."""
    if not request.headers.get("Authorization", "").lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required to link Sign in with Apple")

    claims = await asyncio.to_thread(_verify_apple_identity_token, payload.identity_token)
    apple_sub = claims["sub"].strip()
    verified_email = _apple_claim_email(claims)
    if not verified_email or verified_email != user["email"].lower():
        raise HTTPException(409, "Apple's verified email does not match this WatchSmart account")

    owner = await db.users.find_one({"apple_sub": apple_sub})
    if owner and owner["user_id"] != user["user_id"]:
        raise HTTPException(409, "This Apple account is already linked")
    if user.get("apple_sub") and user["apple_sub"] != apple_sub:
        raise HTTPException(409, "This WatchSmart account is linked to another Apple account")

    apple_refresh_token = await _exchange_apple_authorization_code(
        payload.authorization_code,
        apple_sub,
    )
    try:
        result = await db.users.update_one(
            {
                "user_id": user["user_id"],
                "$or": [
                    {"apple_sub": {"$exists": False}},
                    {"apple_sub": None},
                    {"apple_sub": apple_sub},
                ],
            },
            {
                "$set": {
                    "apple_sub": apple_sub,
                    "apple_refresh_token": apple_refresh_token,
                }
            },
        )
    except DuplicateKeyError:
        raise HTTPException(409, "This Apple account is already linked") from None
    if result.matched_count != 1:
        raise HTTPException(409, "This WatchSmart account could not be linked")
    try:
        await create_user_notification(
            user["user_id"],
            title="Sign in with Apple linked",
            body="You can now use Sign in with Apple for this WatchSmart account.",
            kind="account_security",
            push_body="A new sign-in method was linked to your WatchSmart account.",
            route="/profile",
            dedupe_key=f"apple_linked:{user['user_id']}:{apple_sub}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not create Apple-link account notification: %s", exc)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response, request: Request):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("session_token", path="/")
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    return {"ok": True}


@router.post("/refresh")
async def refresh_access_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "No refresh token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid token type")
        uid = payload["sub"]
        user = await db.users.find_one({"user_id": uid}, {"_id": 0})
        if not user:
            raise HTTPException(401, "User not found")
        # Reject refresh tokens minted before the user's last password change.
        pw_changed = user.get("password_changed_at")
        token_iat = payload.get("iat")
        if pw_changed and token_iat is not None and token_iat < pw_changed:
            raise HTTPException(401, "Refresh token revoked")
        access = create_access_token(uid, user["email"])
        new_refresh = create_refresh_token(uid)
        set_auth_cookies(response, access, new_refresh)
        return {"access_token": access, "refresh_token": new_refresh}
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid refresh token")


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return public_user(dict(user))


@router.post("/change-password")
async def change_password(payload: ChangePasswordIn, request: Request, response: Response, user: dict = Depends(require_user)):
    """Change the authenticated user's password. Requires bearer header (CSRF)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required for this action")
    # require_user strips password_hash, so re-fetch the raw doc to verify.
    raw = await db.users.find_one({"user_id": user["user_id"]})
    if not raw or not raw.get("password_hash"):
        raise HTTPException(400, "Your account uses social sign-in — password change isn't available.")
    if not verify_password(payload.current_password, raw["password_hash"]):
        raise HTTPException(401, "Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(400, "New password must be different from your current password")
    # Bump password_changed_at 1s into the future so any token minted before
    # this point (including the current request's bearer) is rejected. Then
    # mint fresh tokens with iat == password_changed_at so the caller stays
    # signed in on THIS device while every other device gets logged out.
    new_pw_ts = int(datetime.now(timezone.utc).timestamp()) + 1
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "password_hash": hash_password(payload.new_password),
            "password_changed_at": new_pw_ts,
        }},
    )
    await db.user_sessions.delete_many({"user_id": user["user_id"]})
    new_access = create_access_token(user["user_id"], user["email"], iat=new_pw_ts)
    new_refresh = create_refresh_token(user["user_id"], iat=new_pw_ts)
    set_auth_cookies(response, new_access, new_refresh)
    try:
        await create_user_notification(
            user["user_id"],
            title="Password changed",
            body="Your WatchSmart password was changed and other sessions were signed out.",
            kind="account_security",
            push_body="Your WatchSmart password was changed.",
            route="/profile",
            dedupe_key=f"password_changed:{user['user_id']}:{new_pw_ts}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not create password-change notification: %s", exc)
    return {"ok": True, "access_token": new_access, "refresh_token": new_refresh}


@router.delete("/account")
async def delete_account(response: Response, request: Request, user: dict = Depends(require_user)):
    """Permanently delete the authenticated user and all related data.

    CSRF hardening: this destructive endpoint requires a bearer token in the
    Authorization header (set by the SPA via axios). Cookies alone are not
    accepted, so a cross-origin form/image cannot trigger account deletion.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required for this action")

    uid = user["user_id"]
    deletion_lock_owner = f"account-deletion:{uid}:{uuid.uuid4().hex}"

    async def delete_user_data():
        await db.push_devices.update_many(
            {"user_id": uid},
            {"$set": {"active": False, "disabled_reason": "account_deletion"}},
        )
        await db.notification_outbox.update_many(
            {
                "user_id": uid,
                "status": {"$in": ["pending", "retry", "processing"]},
            },
            {"$set": {"status": "cancelled", "updated_at": datetime.now(timezone.utc)}},
        )
        if user.get("apple_sub"):
            apple_record = await db.users.find_one(
                {"user_id": uid},
                {"apple_refresh_token": 1},
            )
            apple_refresh_token = (apple_record or {}).get("apple_refresh_token")
            if not apple_refresh_token:
                raise HTTPException(
                    503,
                    "Sign in with Apple must be used once more before deleting this account.",
                )
            await _revoke_apple_refresh_token(apple_refresh_token)

        failures: list[str] = []
        # Delete dependent collections first and the user document last, so a
        # failed cascade leaves an account that can authenticate and retry.
        for coll, query in [
            ("user_sessions", {"user_id": uid}),
            ("user_actions", {"user_id": uid}),
            ("affiliate_clicks", {"user_id": uid}),
            ("notifications", {"user_id": uid}),
            ("push_devices", {"user_id": uid}),
            ("notification_outbox", {"user_id": uid}),
            ("push_receipts", {"user_id": uid}),
            ("user_reviews", {"user_id": uid}),
            ("friends", {"$or": [{"user_id": uid}, {"friend_id": uid}]}),
            ("share_requests", {"$or": [{"from_user_id": uid}, {"to_user_id": uid}]}),
            ("password_resets", {"user_id": uid}),
            ("plus_interest", {"user_id": uid}),
            ("plus_events", {"user_id": uid}),
            ("plus_launch_deliveries", {"user_id": uid}),
        ]:
            try:
                await getattr(db, coll).delete_many(query)
            except Exception as exc:
                failures.append(f"{coll}: {exc}")

        if failures:
            raise HTTPException(500, f"Account deletion partially failed: {'; '.join(failures)}")

        try:
            await db.users.update_many(
                {"watchlist_friends": uid},
                {"$pull": {"watchlist_friends": uid}},
            )
        except Exception as exc:
            raise HTTPException(500, f"Account relationship cleanup failed: {exc}")

        try:
            await db.users.delete_one({"user_id": uid})
        except Exception as exc:
            raise HTTPException(500, f"Account deletion failed: {exc}")

    try:
        await run_under_user_deletion_fence(
            uid,
            deletion_lock_owner,
            delete_user_data,
            wait_seconds=20,
            lease_seconds=120,
            suppress_release_errors=True,
        )
    except UserDeletionFenceBusy:
        raise HTTPException(503, "Please retry account deletion in a moment")
    except UserNoLongerExists:
        raise HTTPException(401, "Account no longer exists")

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


@router.get("/export")
async def export_account_data(request: Request, user: dict = Depends(require_user)):
    """Return a JSON copy of all data we hold for the authenticated user.

    A basic, self-service data-export flow (GDPR-style "right to access"). Like
    deletion this is gated on a bearer token (CSRF hardening) so a cross-origin
    request carrying only cookies cannot exfiltrate a user's data.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required for this action")

    uid = user["user_id"]

    async def _collect(coll: str, query: dict) -> list:
        try:
            return await getattr(db, coll).find(query, {"_id": 0}).to_list(length=10000)
        except Exception:
            return []

    profile = public_user(
        await db.users.find_one({"user_id": uid}, {"_id": 0, "password_hash": 0})
    )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "reviews": await _collect("user_reviews", {"user_id": uid}),
        "actions": await _collect("user_actions", {"user_id": uid}),
        "notifications": await _collect("notifications", {"user_id": uid}),
        "issue_reports": await _collect("issue_reports", {"user_id": uid}),
        "affiliate_clicks": await _collect("affiliate_clicks", {"user_id": uid}),
        "plus_interest": await _collect("plus_interest", {"user_id": uid}),
        "plus_events": await _collect("plus_events", {"user_id": uid}),
        "plus_launch_deliveries": await _collect("plus_launch_deliveries", {"user_id": uid}),
    }


# ---------------------------------------------------------------------------
# Google OAuth 2.0
# ---------------------------------------------------------------------------

@router.get("/google/url")
async def google_oauth_url(redirect_uri: str):
    """Return the Google OAuth 2.0 authorisation URL for the frontend to redirect to."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(503, "Google sign-in is not configured on this server")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    })
    return {"url": f"https://accounts.google.com/o/oauth2/auth?{params}"}


@router.post("/google/callback")
async def google_callback(request: Request, response: Response):
    """Exchange a Google authorisation code for a WatchSmart session."""
    body = await request.json()
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")
    if not code:
        raise HTTPException(400, "Missing authorisation code")

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(503, "Google sign-in is not configured on this server")

    async with httpx.AsyncClient(timeout=10.0) as http:
        tok_resp = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if tok_resp.status_code != 200:
        raise HTTPException(401, "Failed to exchange Google authorisation code")

    id_token_str = tok_resp.json().get("id_token", "")
    claims = _decode_jwt_payload(id_token_str)
    email = (claims.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(400, "Email not returned by Google")

    return await _upsert_social_user(
        response,
        email=email,
        name=claims.get("name"),
        picture=claims.get("picture"),
        provider="google",
    )


# ---------------------------------------------------------------------------
# Apple Sign In (server-side, form_post)
# ---------------------------------------------------------------------------

@router.get("/apple/url")
async def apple_oauth_url(origin: str):
    """Return the Apple Sign In authorisation URL.

    Apple requires response_mode=form_post, so it POSTs back to a backend
    endpoint rather than a frontend route.  The backend then redirects the
    browser to the correct frontend page after completing sign-in.
    """
    client_id = os.environ.get("APPLE_CLIENT_ID")  # Apple Service ID
    if not client_id:
        raise HTTPException(503, "Apple sign-in is not configured on this server")

    redirect_uri = origin.rstrip("/") + "/api/auth/apple/callback"
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code id_token",
        "scope": "name email",
        "response_mode": "form_post",
    })
    return {"url": f"https://appleid.apple.com/auth/authorize?{params}"}


@router.post("/apple/callback")
async def apple_callback(request: Request, response: Response):
    """The legacy unverified browser callback is intentionally disabled."""
    raise HTTPException(410, "Use the native Sign in with Apple flow")
