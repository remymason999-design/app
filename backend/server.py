"""WatchSmart backend: streaming discovery + savings."""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import uuid
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

import csv
import io
import bcrypt
import jwt
import httpx
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

from emergentintegrations.llm.chat import LlmChat, UserMessage

from movies_seed import SEED_MOVIES, STREAMING_SERVICES, GENRES
import tmdb as tmdb_client

# --- Setup ----------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("watchsmart")

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=200,            # handle high concurrency
    minPoolSize=10,
    waitQueueTimeoutMS=5000,
    serverSelectionTimeoutMS=5000,
)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"
EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"

# In-memory cache of movies — populated from MongoDB (which is seeded from TMDB).
# Falls back to the bundled seed list if DB is empty / TMDB unavailable.
CATALOG: List[dict] = list(SEED_MOVIES)


async def _load_catalog_from_db():
    """Load the movie catalog from MongoDB into the in-memory CATALOG."""
    global CATALOG
    docs = await db.movies_cache.find({}, {"_id": 0}).to_list(length=10000)
    if docs:
        CATALOG = docs
        logger.info(f"Catalog loaded from MongoDB: {len(CATALOG)} titles")
    else:
        CATALOG = list(SEED_MOVIES)
        logger.info(f"Catalog using seed: {len(CATALOG)} titles")


async def _refresh_catalog_from_tmdb(pages: int = 3) -> int:
    """Fetch from TMDB and replace MongoDB cache."""
    items = await tmdb_client.fetch_catalog(pages=pages)
    if not items:
        return 0
    await db.movies_cache.delete_many({})
    if items:
        await db.movies_cache.insert_many([dict(m) for m in items])
    await _load_catalog_from_db()
    return len(items)

app = FastAPI(title="WatchSmart API")
api = APIRouter(prefix="/api")


# --- Helpers --------------------------------------------------------------
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


def set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*7, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*30, path="/")


def clean_user(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    return doc


async def resolve_user(request: Request) -> Optional[dict]:
    # 1) Emergent Google session_token (cookie or Authorization header)
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

    # 2) JWT access token
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


# --- Models ---------------------------------------------------------------
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


class ActionIn(BaseModel):
    movie_id: str
    action: Literal["save", "skip", "watched", "unsave"]


class ExplainIn(BaseModel):
    movie_id: str


# --- Auth endpoints -------------------------------------------------------
@api.post("/auth/register")
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
        "subscriptions": [],
        "genres": [],
        "saved": [],
        "watched": [],
        "skipped": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    access = create_access_token(user_id, email)
    refresh = create_refresh_token(user_id)
    set_auth_cookies(response, access, refresh)
    return {"user": clean_user(doc.copy()), "access_token": access}


@api.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    access = create_access_token(user["user_id"], email)
    refresh = create_refresh_token(user["user_id"])
    set_auth_cookies(response, access, refresh)
    return {"user": clean_user(user), "access_token": access}


@api.post("/auth/logout")
async def logout(response: Response, request: Request):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("session_token", path="/")
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    return {"ok": True}


@api.post("/auth/refresh")
async def refresh_access_token(request: Request, response: Response):
    """Issue a new access token from the refresh_token cookie or Authorization Bearer."""
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
        response.set_cookie(
            "access_token", access, httponly=True, secure=True,
            samesite="none", max_age=60*60*24*7, path="/",
        )
        return {"access_token": access}
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid refresh token")


@api.get("/auth/me")
async def me(user: dict = Depends(require_user)):
    return user


@api.post("/auth/google/session")
async def google_session(response: Response, x_session_id: str = Header(..., alias="X-Session-ID")):
    """Exchange Emergent session_id for our session_token cookie."""
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
            "user_id": user_id,
            "email": email,
            "name": data.get("name") or email.split("@")[0],
            "picture": data.get("picture"),
            "auth_provider": "google",
            "subscriptions": [],
            "genres": [],
            "saved": [],
            "watched": [],
            "skipped": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user.copy())
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
    # Also issue a JWT access token so frontend can use Bearer header fallback
    access = create_access_token(user["user_id"], email)
    return {"user": clean_user(user), "access_token": access}


# --- Reference data -------------------------------------------------------
@api.get("/services")
async def services():
    return STREAMING_SERVICES


@api.get("/genres")
async def genres():
    return GENRES


# --- User preferences -----------------------------------------------------
@api.put("/user/preferences")
async def set_prefs(payload: PreferencesIn, user: dict = Depends(require_user)):
    update = {}
    if payload.services is not None:
        update["subscriptions"] = payload.services
    if payload.genres is not None:
        update["genres"] = payload.genres
    if update:
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return clean_user(fresh)


# --- Movie discovery & actions -------------------------------------------
# Action -> (field, genre_weight_delta)
ACTION_WEIGHTS = {"save": 2, "watched": 3, "skip": -1}


def _movie_matches(movie: dict, user: dict) -> bool:
    subs = set(user.get("subscriptions") or [])
    if subs and not (set(movie.get("available_on", [])) & subs):
        return False
    return True


def _movie_score(movie: dict, user: dict) -> float:
    """Personalised score: base rating + learned weights + onboarding prefs."""
    score = float(movie.get("rating", 7.0)) / 2.0  # max ~5
    mg = set(movie.get("genres", []))
    # Learned genre weights from user's save/watch/skip activity
    gw = user.get("genre_weights") or {}
    learned = sum(gw.get(g, 0) for g in mg) * 0.5
    # Onboarding genre prefs
    prefs = set(user.get("genres") or [])
    overlap = len(mg & prefs)
    # Deterministic jitter per movie for variety without full randomness
    jitter = (hash(movie["id"]) % 100) / 1000.0
    return score + learned + overlap * 1.2 + jitter


def _reason(movie: dict, user: dict) -> str:
    mg = set(movie.get("genres", []))
    gw = user.get("genre_weights") or {}
    # Best-matching learned genre
    top_learned = sorted(((g, gw.get(g, 0)) for g in mg), key=lambda x: x[1], reverse=True)
    if top_learned and top_learned[0][1] >= 2:
        return f"Because you've been loving {top_learned[0][0]}"
    prefs = set(user.get("genres") or [])
    overlap = list(mg & prefs)
    if overlap:
        return f"Matches your {overlap[0]} taste"
    if movie.get("rating", 0) >= 8.5:
        return f"Critically acclaimed · {movie.get('rating')}/10"
    return "Worth a look tonight"


@api.get("/discover")
async def discover(user: dict = Depends(require_user), limit: int = 20):
    seen = set((user.get("saved") or []) + (user.get("watched") or []) + (user.get("skipped") or []))
    pool = [m for m in CATALOG if m["id"] not in seen and _movie_matches(m, user)]
    # Cap scoring work to top-N candidates by popularity to keep latency O(catalog) bounded
    if len(pool) > 500:
        pool.sort(key=lambda m: m.get("popularity", 0), reverse=True)
        pool = pool[:500]
    pool.sort(key=lambda m: _movie_score(m, user), reverse=True)
    out = []
    for m in pool[:limit]:
        item = dict(m)
        item["reason"] = _reason(m, user)
        out.append(item)
    return out


@api.get("/movies/{movie_id}")
async def get_movie(movie_id: str, user: dict = Depends(require_user)):
    m = next((x for x in CATALOG if x["id"] == movie_id), None)
    if not m:
        raise HTTPException(404, "Movie not found")
    return m


@api.post("/user/action")
async def user_action(payload: ActionIn, user: dict = Depends(require_user)):
    movie = next((x for x in CATALOG if x["id"] == payload.movie_id), None)
    if not movie:
        raise HTTPException(404, "Movie not found")
    field_map = {"save": "saved", "skip": "skipped", "watched": "watched"}
    uid = user["user_id"]
    if payload.action == "unsave":
        await db.users.update_one({"user_id": uid}, {"$pull": {"saved": payload.movie_id}})
    else:
        field = field_map[payload.action]
        await db.users.update_one(
            {"user_id": uid},
            {"$addToSet": {field: payload.movie_id},
             "$pull": {f: payload.movie_id for f in ["saved", "skipped", "watched"] if f != field}},
        )
        # Update learned genre weights (only on forward actions, not unsave)
        delta = ACTION_WEIGHTS.get(payload.action, 0)
        if delta:
            inc = {f"genre_weights.{g}": delta for g in movie.get("genres", [])}
            if inc:
                await db.users.update_one({"user_id": uid}, {"$inc": inc})
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    return clean_user(fresh)


def _movies_by_ids(ids: List[str]) -> List[dict]:
    by_id = {m["id"]: m for m in CATALOG}
    return [by_id[i] for i in ids if i in by_id]


@api.get("/watchlist")
async def watchlist(user: dict = Depends(require_user)):
    return _movies_by_ids(user.get("saved") or [])


@api.get("/watched")
async def watched(user: dict = Depends(require_user)):
    return _movies_by_ids(user.get("watched") or [])


# --- Subscription savings -------------------------------------------------
@api.get("/savings")
async def savings(user: dict = Depends(require_user)):
    subs = user.get("subscriptions") or []
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    total = sum(services_by_id.get(s, {}).get("price_monthly", 0) for s in subs)
    saved = user.get("saved") or []
    watched_ids = user.get("watched") or []
    activity_ids = saved + watched_ids
    activity = _movies_by_ids(activity_ids)

    # Usage per subscribed service (count of saved/watched titles available there)
    usage = []
    for sid in subs:
        svc = services_by_id.get(sid)
        if not svc:
            continue
        count = sum(1 for m in activity if sid in m.get("available_on", []))
        # availability for discovery (titles available on this service in seed pool not yet seen)
        seen = set(activity_ids + (user.get("skipped") or []))
        avail_unseen = sum(1 for m in CATALOG
            if sid in m.get("available_on", []) and m["id"] not in seen
        )
        usage.append({
            "service_id": sid,
            "name": svc["name"],
            "logo_color": svc["logo_color"],
            "price_monthly": svc["price_monthly"],
            "activity_count": count,
            "available_unseen": avail_unseen,
        })
    usage.sort(key=lambda x: x["activity_count"])

    # Suggestions: lowest-activity service is candidate for cancellation
    suggestions = []
    if len(usage) >= 2:
        worst = usage[0]
        if worst["activity_count"] <= 1:
            suggestions.append({
                "type": "cancel",
                "service_id": worst["service_id"],
                "headline": f"Cancel {worst['name']} to save ${worst['price_monthly']:.2f}/mo",
                "reason": (
                    f"You've engaged with only {worst['activity_count']} title(s) on {worst['name']}. "
                    "Most of your activity lives on other services."
                ),
                "monthly_savings": worst["price_monthly"],
            })
    # Rotation suggestion if 3+ subs
    if len(subs) >= 3:
        suggestions.append({
            "type": "rotate",
            "headline": "Rotate subscriptions monthly",
            "reason": (
                f"With {len(subs)} services at ${total:.2f}/mo, rotate one in/out each month "
                f"to save up to ${(total/len(subs)):.2f}/mo."
            ),
            "monthly_savings": round(total / len(subs), 2),
        })

    overlap_titles = sum(1 for m in CATALOG if len(set(m.get("available_on", [])) & set(subs)) >= 2)

    return {
        "total_monthly": round(total, 2),
        "total_yearly": round(total * 12, 2),
        "subscription_count": len(subs),
        "usage": usage,
        "suggestions": suggestions,
        "overlap_titles": overlap_titles,
    }


# --- AI explanation -------------------------------------------------------
@api.post("/recommendations/explain")
async def explain(payload: ExplainIn, user: dict = Depends(require_user)):
    movie = next((x for x in CATALOG if x["id"] == payload.movie_id), None)
    if not movie:
        raise HTTPException(404, "Movie not found")
    saved_titles = [m["title"] for m in _movies_by_ids((user.get("saved") or [])[:5])]
    watched_titles = [m["title"] for m in _movies_by_ids((user.get("watched") or [])[:5])]
    user_genres = user.get("genres") or []

    system = (
        "You are WatchSmart, a sharp, friendly streaming concierge. "
        "Write a single concise paragraph (max 55 words) explaining why a specific movie/show "
        "matches the user's taste. Reference the user's preferred genres and recent activity if relevant. "
        "Be specific, never generic. Never use bullet points or markdown."
    )
    prompt = (
        f"Movie: {movie['title']} ({movie['year']})\n"
        f"Genres: {', '.join(movie.get('genres', []))}\n"
        f"Synopsis: {movie['overview']}\n"
        f"User favorite genres: {', '.join(user_genres) or 'unspecified'}\n"
        f"Recently saved: {', '.join(saved_titles) or 'none'}\n"
        f"Recently watched: {', '.join(watched_titles) or 'none'}\n"
        "Write the explanation now."
    )
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return {"explanation": f"You'll likely enjoy {movie['title']} because it leans into {', '.join(movie.get('genres', [])[:2])} — a strong match for your taste."}
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"explain_{user['user_id']}_{movie['id']}",
            system_message=system,
        ).with_model("openai", "gpt-5.2")
        text = await chat.send_message(UserMessage(text=prompt))
        return {"explanation": text.strip()}
    except Exception as e:
        logger.warning(f"GPT-5.2 failed, falling back to Claude: {e}")
        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=f"explain_{user['user_id']}_{movie['id']}",
                system_message=system,
            ).with_model("anthropic", "claude-sonnet-4-5-20250929")
            text = await chat.send_message(UserMessage(text=prompt))
            return {"explanation": text.strip()}
        except Exception as e2:
            logger.error(f"Both LLMs failed: {e2}")
            return {"explanation": f"You'll likely enjoy {movie['title']} because it leans into {', '.join(movie.get('genres', [])[:2])} — a strong match for your taste."}


class ClickIn(BaseModel):
    movie_id: str
    service_id: str


def build_affiliate_url(base_url: str, user_id: str, movie_id: str, service_id: str) -> str:
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
    parsed = urlparse(base_url)
    existing = dict(parse_qsl(parsed.query))
    existing.update({
        "utm_source": "watchsmart",
        "utm_medium": "referral",
        "utm_campaign": "where-to-watch",
        "utm_content": f"{service_id}:{movie_id}",
        "ref": "watchsmart",
        "sub_id": user_id,
    })
    return urlunparse(parsed._replace(query=urlencode(existing)))


@api.post("/affiliate/click")
async def affiliate_click(payload: ClickIn, request: Request, user: dict = Depends(require_user)):
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    svc = services_by_id.get(payload.service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    movie = next((m for m in CATALOG if m["id"] == payload.movie_id), None)
    if not movie:
        raise HTTPException(404, "Movie not found")
    tracked_url = build_affiliate_url(svc["affiliate_url"], user["user_id"], movie["id"], svc["id"])
    await db.affiliate_clicks.insert_one({
        "user_id": user["user_id"],
        "movie_id": movie["id"],
        "movie_title": movie["title"],
        "service_id": svc["id"],
        "service_name": svc["name"],
        "base_url": svc["affiliate_url"],
        "tracked_url": tracked_url,
        "referer": request.headers.get("referer"),
        "user_agent": request.headers.get("user-agent"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"url": tracked_url}


@api.get("/affiliate/me")
async def affiliate_me(user: dict = Depends(require_user)):
    pipeline = [
        {"$match": {"user_id": user["user_id"]}},
        {"$group": {"_id": "$service_id", "count": {"$sum": 1}, "service_name": {"$first": "$service_name"}}},
        {"$sort": {"count": -1}},
    ]
    per_service = []
    async for row in db.affiliate_clicks.aggregate(pipeline):
        per_service.append({
            "service_id": row["_id"],
            "service_name": row.get("service_name"),
            "count": row["count"],
        })
    total = await db.affiliate_clicks.count_documents({"user_id": user["user_id"]})
    return {"total": total, "per_service": per_service}


@api.get("/affiliate/stats")
async def affiliate_stats(user: dict = Depends(require_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    pipeline = [
        {"$group": {
            "_id": "$service_id",
            "count": {"$sum": 1},
            "service_name": {"$first": "$service_name"},
            "unique_users": {"$addToSet": "$user_id"},
        }},
        {"$project": {"service_id": "$_id", "service_name": 1, "count": 1, "unique_users": {"$size": "$unique_users"}, "_id": 0}},
        {"$sort": {"count": -1}},
    ]
    per_service = []
    async for row in db.affiliate_clicks.aggregate(pipeline):
        per_service.append(row)
    total_clicks = await db.affiliate_clicks.count_documents({})
    total_users = len(await db.affiliate_clicks.distinct("user_id"))
    return {"total_clicks": total_clicks, "unique_users": total_users, "per_service": per_service}


@api.get("/affiliate/export.csv")
async def affiliate_export_csv(user: dict = Depends(require_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "created_at", "user_id", "service_id", "service_name",
        "movie_id", "movie_title", "tracked_url", "referer", "user_agent",
    ])
    cursor = db.affiliate_clicks.find({}, {"_id": 0}).sort("created_at", -1)
    async for r in cursor:
        writer.writerow([
            r.get("created_at"), r.get("user_id"), r.get("service_id"), r.get("service_name"),
            r.get("movie_id"), r.get("movie_title"), r.get("tracked_url"),
            r.get("referer", ""), r.get("user_agent", ""),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=watchsmart_affiliate_clicks.csv"},
    )


@api.get("/")
async def root():
    return {"app": "WatchSmart", "status": "ok", "catalog_size": len(CATALOG)}


# --- Admin -----------------------------------------------------------------
@api.post("/admin/refresh-catalog")
async def admin_refresh_catalog(user: dict = Depends(require_user), pages: int = 3):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    try:
        n = await _refresh_catalog_from_tmdb(pages=pages)
        return {"ok": True, "count": n}
    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        raise HTTPException(502, f"TMDB refresh failed: {e}")


@api.get("/admin/dashboard")
async def admin_dashboard(user: dict = Depends(require_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    total_users = await db.users.count_documents({})
    total_clicks = await db.affiliate_clicks.count_documents({})
    unique_click_users = len(await db.affiliate_clicks.distinct("user_id"))
    pipeline = [
        {"$group": {"_id": "$service_id", "count": {"$sum": 1}, "service_name": {"$first": "$service_name"}}},
        {"$sort": {"count": -1}},
    ]
    by_service = []
    async for row in db.affiliate_clicks.aggregate(pipeline):
        by_service.append({"service_id": row["_id"], "service_name": row.get("service_name"), "count": row["count"]})
    # Recent clicks
    recent = []
    async for r in db.affiliate_clicks.find({}, {"_id": 0}).sort("created_at", -1).limit(20):
        recent.append({
            "created_at": r.get("created_at"),
            "user_id": r.get("user_id"),
            "service_name": r.get("service_name"),
            "movie_title": r.get("movie_title"),
        })
    return {
        "catalog_size": len(CATALOG),
        "total_users": total_users,
        "total_clicks": total_clicks,
        "unique_click_users": unique_click_users,
        "by_service": by_service,
        "recent": recent,
    }


# --- App config -----------------------------------------------------------
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.movies_cache.create_index("id", unique=True)
    await db.affiliate_clicks.create_index("created_at")
    # Seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@watchsmart.app").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": admin_email,
            "name": "Admin",
            "password_hash": hash_password(admin_password),
            "picture": None,
            "auth_provider": "password",
            "role": "admin",
            "subscriptions": ["netflix", "hbo_max", "prime_video"],
            "genres": ["Drama", "Sci-Fi"],
            "saved": [],
            "watched": [],
            "skipped": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded admin: {admin_email}")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
    elif existing.get("role") != "admin":
        await db.users.update_one({"email": admin_email}, {"$set": {"role": "admin"}})

    # Load catalog from DB; if empty, try TMDB seed in background
    await _load_catalog_from_db()
    if len(CATALOG) <= len(SEED_MOVIES) and os.environ.get("TMDB_BEARER_TOKEN"):
        import asyncio
        async def _bg():
            try:
                n = await _refresh_catalog_from_tmdb(pages=3)
                logger.info(f"TMDB catalog seeded: {n} titles")
            except Exception as e:
                logger.warning(f"Initial TMDB seed failed (continuing with bundled seed): {e}")
        asyncio.create_task(_bg())


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
