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
from catalog_import import bulk_import_catalog, enrich_providers_top
from routers import auth, user, discovery, content, reviews, notifications, affiliate, admin, savings, recommendations, insights, password_reset, sharing, onboarding
from routers import debug_genre, reports, pricing, avatar, monetization
from pricing import seed_pricing_plans
from push_notifications import run_push_worker
from rate_limit import limiter, rate_limit_handler
from slowapi.errors import RateLimitExceeded

import uuid

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Error tracking (Sentry) — no-op unless SENTRY_DSN is configured.
_sentry_dsn = os.environ.get("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
    logger.info("Sentry error tracking initialised")

app = FastAPI(title="WatchSmart API")
push_worker_task = None


def _legacy_onboarding_backfill_filter() -> dict:
    """Match only missing-state accounts with established legacy activity."""
    return {
        "onboarding_completed": {"$exists": False},
        "onboarding_rated": {"$exists": False},
        "onboarding_genre_weights": {"$exists": False},
        "onboarding_type_weights": {"$exists": False},
        "onboarding_tone_weights": {"$exists": False},
        "onboarding_pacing_weights": {"$exists": False},
        "onboarding_theme_weights": {"$exists": False},
        "onboarding_language_weights": {"$exists": False},
        "onboarding_decade_weights": {"$exists": False},
        "onboarding_cast_weights": {"$exists": False},
        "onboarding_director_weights": {"$exists": False},
        "onboarding_writer_weights": {"$exists": False},
        "onboarding_runtime_weights": {"$exists": False},
        "onboarding_popularity_weights": {"$exists": False},
        "onboarding_quality_pref_weights": {"$exists": False},
        "$or": [
            {"saved.0": {"$exists": True}},
            {"watched.0": {"$exists": True}},
            {"skipped.0": {"$exists": True}},
            {"genre_weights": {"$exists": True, "$ne": {}}},
            {"type_weights": {"$exists": True, "$ne": {}}},
            {"tone_weights": {"$exists": True, "$ne": {}}},
            {"theme_weights": {"$exists": True, "$ne": {}}},
            {"taste_profile": {"$exists": True}},
        ],
    }


# Abuse protection: register the shared slowapi limiter + friendly 429 handler.
# Per-route limits are applied via @limiter.limit(...) on sensitive endpoints
# (auth, password reset, issue reports).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

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
api.include_router(debug_genre.router)
api.include_router(reports.router)
api.include_router(pricing.router)
api.include_router(avatar.router)
api.include_router(monetization.router)


@api.get("/")
async def root():
    return {"app": "WatchSmart", "status": "ok", "catalog_size": len(get_catalog())}


app.include_router(api)

_cors_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_default_origins = [
    "http://localhost:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    # Expo dev server (native app development / Expo web preview)
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins or _default_origins,
    allow_origin_regex=r"https://[a-z0-9\-]+\.(replit\.dev|picard\.replit\.dev)",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Production static serving
# ---------------------------------------------------------------------------
# Serve the built React app from FastAPI so the whole product is a single
# origin (no CORS, no second server). The API router above is registered first
# and lives under /api, so it always takes precedence over the SPA catch-all.
#
# In development the build directory does not exist (the CRA dev server serves
# the frontend instead), so this whole block is a no-op and the backend behaves
# exactly as before.
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

FRONTEND_BUILD = (Path(__file__).resolve().parent.parent / "frontend" / "build")
if FRONTEND_BUILD.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_BUILD / "static"),
        name="static",
    )

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Never hijack the API — let unmatched /api paths return a JSON 404
        # instead of the HTML shell.
        if full_path.startswith("api"):
            raise StarletteHTTPException(status_code=404)
        build_root = FRONTEND_BUILD.resolve()
        candidate = (build_root / full_path).resolve()
        # Serve a real static file when it exists (guarding against path
        # traversal); otherwise fall back to index.html so client-side React
        # Router routes resolve on a hard refresh / deep link.
        if full_path and candidate.is_file() and candidate.is_relative_to(build_root):
            return FileResponse(candidate)
        return FileResponse(build_root / "index.html")

    logger.info("Serving production frontend build from %s", FRONTEND_BUILD)
else:
    logger.info(
        "No frontend build at %s — static serving disabled (development mode)",
        FRONTEND_BUILD,
    )


@app.on_event("startup")
async def on_startup():
    # Fail loudly if the database is unreachable, rather than limping along and
    # appearing to lose data. A persistent, reachable Mongo is a hard
    # requirement for the app to be safe to serve.
    try:
        await db.command("ping")
    except Exception as exc:  # noqa: BLE001
        logger.error("DATABASE UNREACHABLE at startup: %s — refusing to mask data loss.", exc)
        raise

    # dbPath inspection is best-effort only: getCmdLineOpts is unavailable or
    # unauthorized on managed clusters (e.g. Atlas), so it must never abort a
    # startup whose ping already succeeded.
    dbpath = None
    try:
        opts = await db.client.admin.command("getCmdLineOpts")
        dbpath = (opts.get("parsed", {}).get("storage", {}) or {}).get("dbPath")
    except Exception:  # noqa: BLE001
        dbpath = None
    if dbpath and dbpath.startswith("/tmp"):
        logger.error(
            "DATABASE WARNING: mongod dbPath is %s (ephemeral /tmp) — user data "
            "will be LOST on container recycle. Use a persistent path or a "
            "managed cluster (set MONGO_URL).", dbpath,
        )
    else:
        logger.info("MongoDB reachable (ping ok, dbPath=%s)", dbpath or "managed/remote")

    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("apple_sub", unique=True, sparse=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.movies_cache.create_index("id", unique=True)
    # Search-supporting indexes — speed up /search across the full catalog.
    await db.movies_cache.create_index([("popularity", -1)])
    await db.movies_cache.create_index("year")
    await db.movies_cache.create_index("genres")
    await db.movies_cache.create_index("keywords")
    await db.movies_cache.create_index("available_on")
    await db.movies_cache.create_index("rent_on")
    await db.movies_cache.create_index("buy_on")
    # Cast/crew/studio search indexes — make actor/director/studio queries fast.
    await db.movies_cache.create_index("cast_names")
    await db.movies_cache.create_index("director_names")
    await db.movies_cache.create_index("writer_names")
    await db.movies_cache.create_index("studio_names")
    # Aliases (alt / original / regional titles) and franchise collections —
    # required so /search can match "The Simpsons Movie", "Harry Potter", etc.
    await db.movies_cache.create_index("aliases")
    await db.movies_cache.create_index("collections")
    await db.affiliate_clicks.create_index("created_at")
    await db.user_actions.create_index([("user_id", 1), ("created_at", -1)])
    # Community metric refreshes scan recent, impression-linked actions and
    # impressions. Keep these exact query shapes indexed as the logs grow.
    await db.user_actions.create_index(
        [("created_at", 1), ("movie_id", 1), ("impression_id", 1)]
    )
    await db.user_actions.create_index(
        [("movie_id", 1), ("impression_id", 1), ("created_at", 1)]
    )
    await db.impressions.create_index(
        [("at", 1), ("impression_id", 1), ("items.id", 1)]
    )
    await db.impressions.create_index(
        [("items.id", 1), ("at", 1), ("impression_id", 1)]
    )
    await db.user_reviews.create_index([("movie_id", 1), ("user_id", 1)], unique=True)
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.push_devices.create_index("expo_token", unique=True)
    await db.push_devices.create_index("installation_id", unique=True)
    await db.push_devices.create_index([("user_id", 1), ("active", 1)])
    await db.push_devices.create_index("expires_at")
    await db.notification_outbox.create_index("dedupe_key", unique=True, sparse=True)
    await db.notification_outbox.create_index([("status", 1), ("next_attempt_at", 1)])
    await db.push_receipts.create_index("ticket_id", unique=True)
    await db.push_receipts.create_index([("status", 1), ("check_after", 1)])
    await db.push_receipts.create_index("user_id")
    await db.push_delivery_locks.create_index("user_id", unique=True)
    await db.push_delivery_locks.create_index("expires_at", expireAfterSeconds=0)
    await db.notifications.create_index("dedupe_key", unique=True, sparse=True)

    await db.password_resets.create_index("token", unique=True)
    await db.password_resets.create_index("expires_at")
    await db.share_requests.create_index("request_id", unique=True)
    await db.share_requests.create_index([("to_user_id", 1), ("status", 1), ("created_at", -1)])
    await db.share_requests.create_index([("from_user_id", 1), ("status", 1)])
    await db.users.create_index("share_code", unique=True, sparse=True)

    await db.issue_reports.create_index([("status", 1), ("created_at", -1)])
    await db.issue_reports.create_index([("movie_id", 1), ("user_id", 1), ("reason", 1)])

    # Profile-photo avatars — one binary doc per user (unique user_id).
    await db.avatars.create_index("user_id", unique=True)
    # WatchSmart+ launch interest is one current record per authenticated user.
    await db.plus_interest.create_index("user_id", unique=True)
    # Event IDs make client retries and screen remounts deduplicable.
    await db.plus_events.create_index("event_id", unique=True)
    await db.plus_events.create_index([("event_name", 1), ("created_at", -1)])
    await db.plus_events.create_index([("user_id", 1), ("created_at", -1)])
    await db.plus_launch_state.create_index("campaign_id", unique=True)
    await db.plus_launch_deliveries.create_index("delivery_key", unique=True)
    await db.plus_launch_deliveries.create_index(
        [("campaign_id", 1), ("channel", 1), ("status", 1)]
    )

    # UK streaming plan pricing — index the doc key and seed the canonical
    # table. Seeding is idempotent and preserves admin edits (see pricing.py).
    await db.streaming_plans.create_index("id", unique=True)
    await db.streaming_plans.create_index([("service_id", 1), ("active", 1)])
    try:
        _seed_summary = await seed_pricing_plans(db)
        logger.info("Streaming plans seeded: %s", _seed_summary)
    except Exception as exc:  # noqa: BLE001
        logger.error("Streaming plan seeding failed (non-fatal): %s", exc)

    # Seed admin — credentials come from environment secrets only. There is no
    # hardcoded default password: if ADMIN_PASSWORD is unset we never create or
    # reset an admin to a guessable value (a known default on a public beta is a
    # takeover vector). Set the ADMIN_PASSWORD secret (and optionally ADMIN_EMAIL)
    # to provision the admin account.
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@watchsmart.app").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD")
    existing = await db.users.find_one({"email": admin_email})
    if not admin_password:
        if existing and existing.get("role") != "admin":
            await db.users.update_one({"email": admin_email}, {"$set": {"role": "admin"}})
        logger.warning(
            "ADMIN_PASSWORD secret not set — admin credentials are not managed "
            "and no default password is applied. Set the ADMIN_PASSWORD secret "
            "to provision/rotate the admin account."
        )
    elif not existing:
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
        logger.info("Seeded admin account from environment credentials")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
    elif existing.get("role") != "admin":
        await db.users.update_one({"email": admin_email}, {"$set": {"role": "admin"}})

    # Conservative legacy migration.  A missing flag alone is not evidence that
    # someone predates onboarding: freshly registered accounts intentionally
    # begin without it.  Only accounts with pre-existing behavioral/taste
    # evidence are safely treated as legacy; in-progress onboarding source
    # fields are explicitly excluded.
    await db.users.update_many(
        _legacy_onboarding_backfill_filter(),
        {"$set": {"onboarding_completed": True}},
    )

    global push_worker_task
    push_worker_task = asyncio.create_task(run_push_worker())

    await load_catalog_from_db()
    if os.environ.get("TMDB_BEARER_TOKEN"):
        async def _bg():
            try:
                db_count = await db.movies_cache.count_documents({})

                if db_count < 5000:
                    # Cold start or very small catalog — run the full genre-balanced
                    # import with generous pagination so every genre gets real depth.
                    logger.info(
                        f"Catalog small ({db_count} in DB) — starting full genre-balanced import "
                        f"({len(__import__('catalog_import').GENERAL_ENDPOINTS)} general + "
                        f"{len(__import__('catalog_import').GENRE_ENDPOINTS)} genre endpoints)…"
                    )
                    result = await bulk_import_catalog(
                        db, pages_general=10, pages_genre=5
                    )
                    logger.info(
                        f"Full import done: {result['unique']} unique titles, "
                        f"{result['total_in_db']} total in DB"
                    )
                    await load_catalog_from_db()
                    logger.info(f"Catalog reloaded: {len(get_catalog())} titles in memory")

                elif db_count < 12000:
                    # Moderate catalog — light top-up to catch new releases and fill
                    # any genre gaps from a previous partial run.
                    logger.info(
                        f"Catalog moderate ({db_count} in DB) — running genre top-up "
                        f"(pages_general=3, pages_genre=2)…"
                    )
                    result = await bulk_import_catalog(
                        db, pages_general=3, pages_genre=2
                    )
                    await load_catalog_from_db()
                    logger.info(
                        f"Top-up done: {result['total_in_db']} in DB, "
                        f"{len(get_catalog())} in memory"
                    )

                else:
                    logger.info(f"Catalog healthy ({db_count} in DB) — skipping bulk import")

                # Enrich provider data for the top un-enriched titles.
                # 3 000 covers ~rank 3 000 by popularity; subsequent startups
                # will enrich the next 3 000 and so on until all are done.
                enriched = await enrich_providers_top(db, limit=3000, region="GB")
                logger.info(f"Provider enrichment pass done: {enriched} titles updated")

                # Backfill cast/director/writer/studio for any titles that lack
                # it or carry an old metadata_version. Resumable: selector only
                # catches docs missing the current version; re-runs are cheap.
                from cast_backfill import backfill_credits
                cb = await backfill_credits(limit=5000, concurrency=16)
                logger.info(f"Cast/director/writer backfill done: {cb} titles updated")

                # Final reload so in-memory catalog reflects freshly enriched data
                await load_catalog_from_db()

            except Exception as e:
                logger.warning(f"Background catalog sync failed (non-fatal): {e}", exc_info=True)
        asyncio.create_task(_bg())


@app.on_event("shutdown")
async def on_shutdown():
    if push_worker_task:
        push_worker_task.cancel()
        try:
            await push_worker_task
        except asyncio.CancelledError:
            pass
    mongo_client.close()
