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
from routers import auth, user, discovery, content, reviews, notifications, affiliate, admin, savings, recommendations, insights, password_reset, sharing, onboarding

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
api.include_router(password_reset.router)
api.include_router(sharing.router)
api.include_router(onboarding.router)


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

    await db.password_resets.create_index("token", unique=True)
    await db.password_resets.create_index("expires_at")
    await db.share_requests.create_index("request_id", unique=True)
    await db.share_requests.create_index([("to_user_id", 1), ("status", 1), ("created_at", -1)])
    await db.share_requests.create_index([("from_user_id", 1), ("status", 1)])
    await db.users.create_index("share_code", unique=True, sparse=True)

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

    # Backfill: mark pre-existing users as onboarded so they don't get re-prompted
    # by the new 4-step onboarding flow. New users will go through it normally.
    await db.users.update_many(
        {"onboarding_completed": {"$exists": False}},
        {"$set": {"onboarding_completed": True}},
    )

    await load_catalog_from_db()
    if os.environ.get("TMDB_BEARER_TOKEN"):
        # Always schedule a deep TMDB sync in the background — non-blocking.
        # The first run after deploy grows the catalog from ~360 to 1500-2500
        # titles to support the engine's 2000-item target pool.
        async def _bg():
            try:
                from engine import LOW_WATER as _LW  # avoid import at module load
                # Only deep-refresh if we look small or stale
                if len(get_catalog()) < 1500:
                    n = await refresh_catalog_from_tmdb(pages=8)
                    logger.info(f"TMDB deep-sync complete: {n} titles")
            except Exception as e:
                logger.warning(f"Initial TMDB deep-sync failed (continuing): {e}")
        asyncio.create_task(_bg())


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()
