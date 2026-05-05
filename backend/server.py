"""WatchSmart backend entrypoint — wires routers + lifecycle."""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from core import (
    db, mongo_client, logger,
    load_catalog_from_db, refresh_catalog_from_tmdb,
    hash_password, verify_password, get_catalog,
    SEED_MOVIES,
)
from routers import auth, user, discovery, content, reviews, notifications, affiliate, admin, savings, recommendations, insights

import uuid

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI(title="WatchSmart API")
api = APIRouter(prefix="/api")

# Mount feature routers
api.include_router(auth.router)
api.include_router(user.router)
api.include_router(discovery.router)
api.include_router(content.router)
api.include_router(reviews.router)
api.include_router(notifications.router)
api.include_router(affiliate.router)
api.include_router(admin.router)
api.include_router(savings.router)
api.include_router(recommendations.router)
api.include_router(insights.router)


@api.get("/")
async def root():
    return {"app": "WatchSmart", "status": "ok", "catalog_size": len(get_catalog())}


app.include_router(api)

_cors_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins or ["http://localhost:3000"],
    allow_origin_regex=r"https://[a-z0-9\-]+\.preview\.emergentagent\.com",
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
    await db.user_actions.create_index([("user_id", 1), ("created_at", -1)])
    await db.user_actions.create_index("created_at")
    await db.user_reviews.create_index([("movie_id", 1), ("user_id", 1)], unique=True)
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])

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
            "saved": [], "watched": [], "skipped": [],
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

    await load_catalog_from_db()
    if len(get_catalog()) <= len(SEED_MOVIES) and os.environ.get("TMDB_BEARER_TOKEN"):
        async def _bg():
            try:
                n = await refresh_catalog_from_tmdb(pages=3)
                logger.info(f"TMDB catalog seeded: {n} titles")
            except Exception as e:
                logger.warning(f"Initial TMDB seed failed (continuing with bundled seed): {e}")
        asyncio.create_task(_bg())


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()
