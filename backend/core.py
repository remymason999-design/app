"""Shared core: db, models, dependencies, helpers, in-memory CATALOG."""
import os
import uuid
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

import bcrypt
import jwt
import httpx
from fastapi import Request, Response, HTTPException, Depends, Header
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

from movies_seed import SEED_MOVIES, STREAMING_SERVICES, GENRES
import tmdb as tmdb_client

logger = logging.getLogger("watchsmart")

# --- Mongo ----------------------------------------------------------------
mongo_url = os.environ['MONGO_URL']
mongo_client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=200, minPoolSize=10,
    waitQueueTimeoutMS=5000, serverSelectionTimeoutMS=5000,
)
db = mongo_client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"
EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"

# --- In-memory catalog ----------------------------------------------------
CATALOG: List[dict] = list(SEED_MOVIES)


async def load_catalog_from_db() -> None:
    global CATALOG
    docs = await db.movies_cache.find({}, {"_id": 0}).to_list(length=10000)
    if docs:
        CATALOG = docs
    else:
        CATALOG = list(SEED_MOVIES)
    # Attach content cards (idempotent — only fills `card` if missing)
    from content_cards import attach_cards
    attach_cards(CATALOG)
    logger.info(f"Catalog loaded: {len(CATALOG)} titles (cards attached)")


async def refresh_catalog_from_tmdb(pages: int = 3) -> int:
    items = await tmdb_client.fetch_catalog(pages=pages)
    if not items:
        return 0
    # Idempotent upsert avoids duplicate-key races when two refreshes run concurrently
    from pymongo import UpdateOne
    ops = [
        UpdateOne({"id": m["id"]}, {"$set": {k: v for k, v in m.items() if k != "_id"}}, upsert=True)
        for m in items
    ]
    if ops:
        try:
            await db.movies_cache.bulk_write(ops, ordered=False)
        except Exception as e:
            logger.warning(f"bulk_write had non-fatal errors: {type(e).__name__}")
    await load_catalog_from_db()
    return len(items)


def get_catalog() -> List[dict]:
    return CATALOG


def movies_by_ids(ids: List[str]) -> List[dict]:
    by_id = {m["id"]: m for m in CATALOG}
    return [by_id[i] for i in ids if i in by_id]


def find_movie(movie_id: str) -> Optional[dict]:
    return next((x for x in CATALOG if x["id"] == movie_id), None)


# --- Auth helpers ---------------------------------------------------------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    return jwt.encode(
        {"sub": user_id, "email": email, "type": "access",
         "exp": datetime.now(timezone.utc) + timedelta(days=7)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "type": "refresh",
         "exp": datetime.now(timezone.utc) + timedelta(days=30)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*7, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*30, path="/")


def clean_user(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return doc
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    return doc


async def resolve_user(request: Request) -> Optional[dict]:
    # Emergent Google session_token
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:].startswith("emg_"):
            session_token = auth[7:]
    if session_token:
        sess = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
        if sess:
            exp = sess.get("expires_at")
            if isinstance(exp, str):
                exp = datetime.fromisoformat(exp)
            if exp and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp and exp >= datetime.now(timezone.utc):
                user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
                if user:
                    return clean_user(user)

    # JWT access token
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        user = await db.users.find_one({"user_id": payload["sub"]}, {"_id": 0})
        return clean_user(user) if user else None
    except jwt.PyJWTError:
        return None


async def require_user(request: Request) -> dict:
    u = await resolve_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u


async def require_admin(user: dict = Depends(require_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# --- Pydantic models ------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PreferencesIn(BaseModel):
    services: Optional[List[str]] = None
    genres: Optional[List[str]] = None
    moods: Optional[List[str]] = None
    excluded_categories: Optional[List[str]] = None
    excluded_genres: Optional[List[str]] = None
    content_type: Optional[Literal["movie", "tv", "both"]] = None
    country: Optional[str] = None
    age: Optional[int] = None
    onboarding_completed: Optional[bool] = None


class ProgressIn(BaseModel):
    movie_id: str
    season: int = Field(ge=1, le=200)
    episode: int = Field(ge=1, le=999)


class ReviewIn(BaseModel):
    movie_id: str
    rating: int = Field(ge=1, le=10)
    text: str = Field(min_length=1, max_length=2000)


class ActionIn(BaseModel):
    movie_id: str
    action: Literal["save", "skip", "watched", "unsave"]


class ExplainIn(BaseModel):
    movie_id: str


class ClickIn(BaseModel):
    movie_id: str
    service_id: str


# --- Recommendation engine -----------------------------------------------
ACTION_WEIGHTS = {"save": 2, "watched": 3, "skip": -1}


def movie_matches(movie: dict, user: dict) -> bool:
    """Strict match: subscription + excluded categories + content_type + excluded_genres.

    Anime is detected via the 'anime' tag (Japanese animation only) — Pixar/family
    animation does NOT carry the 'anime' tag.
    """
    subs = set(user.get("subscriptions") or [])
    if subs and not (set(movie.get("available_on", [])) & subs):
        return False
    excluded = set(user.get("excluded_categories") or [])
    if excluded and (set(movie.get("tags") or []) & excluded):
        return False
    # Content type filter: "movie" | "tv" | "both" (default both)
    content_type = user.get("content_type")
    if content_type and content_type != "both":
        if movie.get("type") != content_type:
            return False
    # Explicit excluded genres
    excluded_genres = set(user.get("excluded_genres") or [])
    if excluded_genres and (set(movie.get("genres") or []) & excluded_genres):
        return False
    return True


def movie_score(movie: dict, user: dict) -> float:
    """Personalised score: rating + learned + onboarding + recency boost."""
    score = float(movie.get("rating", 7.0)) / 2.0
    # Demote low-vote-count titles (fewer than 100 votes = niche, not surfaced early)
    if (movie.get("vote_count") or 0) < 50:
        score -= 0.5

    mg = set(movie.get("genres", []))
    gw = user.get("genre_weights") or {}
    learned = sum(gw.get(g, 0) for g in mg) * 0.5

    prefs = set(user.get("genres") or [])
    overlap = len(mg & prefs)

    # Content-type preference (movie vs tv)
    type_pref = (user.get("type_weights") or {}).get(movie.get("type"), 0)

    # Recency: newer titles get a slight boost (within 2 years)
    year = movie.get("year") or 0
    current = datetime.now(timezone.utc).year
    if year and (current - year) <= 2:
        score += 0.4

    jitter = (hash(movie["id"]) % 100) / 1000.0
    return score + learned + overlap * 1.2 + type_pref * 0.3 + jitter


def movie_reason(movie: dict, user: dict) -> str:
    mg = set(movie.get("genres", []))
    gw = user.get("genre_weights") or {}
    top_learned = sorted(((g, gw.get(g, 0)) for g in mg), key=lambda x: x[1], reverse=True)
    if top_learned and top_learned[0][1] >= 2:
        return f"Because you've been loving {top_learned[0][0]}"
    prefs = set(user.get("genres") or [])
    overlap = list(mg & prefs)
    if overlap:
        return f"Matches your {overlap[0]} taste"
    if (movie.get("rating") or 0) >= 8.5:
        return f"Critically acclaimed · {movie.get('rating')}/10"
    return "Worth a look tonight"


# --- TMDB section cache (10-min TTL) -------------------------------------
_SECTION_CACHE: dict = {}
_SECTION_TTL = 600


async def cached_section(path: str, kind: str, region: str, pages: int = 1):
    key = (path, region)
    now = time.time()
    cached = _SECTION_CACHE.get(key)
    if cached and (now - cached[0]) < _SECTION_TTL:
        return cached[1]
    items = await tmdb_client.fetch_endpoint(path, kind, pages=pages, region=region)
    _SECTION_CACHE[key] = (now, items)
    return items


def apply_user_filters(items: list, user: dict) -> list:
    """Applied to TMDB section results (trending/upcoming/popular).

    Strict filters — if user excluded anime/bollywood or set content_type=tv,
    those items MUST be dropped from every feed, not just Discover.
    """
    excluded = set(user.get("excluded_categories") or [])
    excluded_genres = set(user.get("excluded_genres") or [])
    content_type = user.get("content_type")
    out = []
    for m in items:
        if excluded and (set(m.get("tags") or []) & excluded):
            continue
        if excluded_genres and (set(m.get("genres") or []) & excluded_genres):
            continue
        if content_type and content_type != "both" and m.get("type") != content_type:
            continue
        out.append(m)
    return out


# --- Seed welcome notifications ------------------------------------------
async def seed_notifications_for_user(user_id: str) -> None:
    existing = await db.notifications.count_documents({"user_id": user_id})
    if existing >= 3:
        return
    seed = [
        {"title": "Welcome to WatchSmart", "body": "Swipe right to save, left to skip. We'll learn your taste in minutes.", "kind": "welcome"},
        {"title": "Trending this week", "body": "Tap Trending in Discover to see what everyone's watching right now.", "kind": "trending"},
        {"title": "You can save real money", "body": "Open Savings to see which subscriptions are pulling their weight.", "kind": "tip"},
    ]
    docs = [{
        "user_id": user_id,
        "title": s["title"], "body": s["body"], "kind": s["kind"],
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    } for s in seed]
    if docs:
        await db.notifications.insert_many(docs)


__all__ = [
    "db", "JWT_SECRET", "JWT_ALGORITHM", "EMERGENT_AUTH_URL",
    "logger", "tmdb_client",
    "load_catalog_from_db", "refresh_catalog_from_tmdb", "get_catalog",
    "movies_by_ids", "find_movie", "CATALOG",
    "hash_password", "verify_password", "create_access_token", "create_refresh_token",
    "set_auth_cookies", "clean_user", "resolve_user", "require_user", "require_admin",
    "RegisterIn", "LoginIn", "PreferencesIn", "ProgressIn", "ReviewIn", "ActionIn", "ExplainIn", "ClickIn",
    "ACTION_WEIGHTS", "movie_matches", "movie_score", "movie_reason",
    "cached_section", "apply_user_filters", "seed_notifications_for_user",
    "SEED_MOVIES", "STREAMING_SERVICES", "GENRES",
    "httpx", "uuid", "datetime", "timezone", "timedelta",
]
