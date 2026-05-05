"""Auth router."""
import os
from fastapi import APIRouter, Request, Response, HTTPException, Depends, Header

import jwt
from datetime import datetime, timezone, timedelta

from core import (
    db, EMERGENT_AUTH_URL, JWT_SECRET, JWT_ALGORITHM,
    RegisterIn, LoginIn,
    hash_password, verify_password,
    create_access_token, create_refresh_token, set_auth_cookies,
    clean_user, require_user,
    seed_notifications_for_user, httpx,
)
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register(payload: RegisterIn, response: Response):
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    await seed_notifications_for_user(user_id)
    access = create_access_token(user_id, email)
    refresh = create_refresh_token(user_id)
    set_auth_cookies(response, access, refresh)
    return {"user": clean_user(doc.copy()), "access_token": access}


@router.post("/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    access = create_access_token(user["user_id"], email)
    refresh = create_refresh_token(user["user_id"])
    set_auth_cookies(response, access, refresh)
    return {"user": clean_user(user), "access_token": access}


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
        access = create_access_token(uid, user["email"])
        response.set_cookie("access_token", access, httponly=True, secure=True,
                            samesite="none", max_age=60*60*24*7, path="/")
        return {"access_token": access}
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid refresh token")


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return user


@router.post("/google/session")
async def google_session(response: Response, x_session_id: str = Header(..., alias="X-Session-ID")):
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get(EMERGENT_AUTH_URL, headers={"X-Session-ID": x_session_id})
    if r.status_code != 200:
        raise HTTPException(401, "Invalid Emergent session")
    data = r.json()
    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(400, "Email missing from Emergent session")
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id, "email": email,
            "name": data.get("name") or email.split("@")[0],
            "picture": data.get("picture"),
            "auth_provider": "google",
            "subscriptions": [], "genres": [],
            "saved": [], "watched": [], "skipped": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user.copy())
        await seed_notifications_for_user(user["user_id"])
    session_token = data.get("session_token")
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": expires.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    response.set_cookie("session_token", session_token, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*7, path="/")
    access = create_access_token(user["user_id"], email)
    return {"user": clean_user(user), "access_token": access}
