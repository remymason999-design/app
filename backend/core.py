"""Shared core: db, models, dependencies, helpers, in-memory CATALOG."""
import os
import uuid
import logging
import time
import hashlib
from datetime import datetime, date, timezone, timedelta
from typing import List, Optional, Literal

import bcrypt
import jwt
import httpx
from fastapi import Request, Response, HTTPException, Depends, Header
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

from movies_seed import SEED_MOVIES, STREAMING_SERVICES, GENRES
from providers_util import resolve_region_providers
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

# Prefer the dedicated JWT signing key, but do not make the entire production
# service unbootable if that optional secret is removed. SESSION_SECRET is
# already required by the application and is suitable key material for signing.
# A fallback does rotate the JWT key, so existing tokens minted with a lost
# JWT_SECRET cannot be recovered; users sign in once and receive stable tokens.
JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ["SESSION_SECRET"]
if "JWT_SECRET" not in os.environ:
    logger.warning(
        "JWT_SECRET is not configured; using SESSION_SECRET for JWT signing. "
        "Set JWT_SECRET explicitly to avoid accidental signing-key rotation."
    )
JWT_ALGORITHM = "HS256"

# --- In-memory catalog ----------------------------------------------------
CATALOG: List[dict] = list(SEED_MOVIES)


async def load_catalog_from_db() -> None:
    global CATALOG
    docs = await db.movies_cache.find({}, {"_id": 0}).to_list(length=10000)
    if docs:
        # Seed movies are always present; DB docs (TMDB) take priority by title+year.
        # This prevents losing known titles when the DB only has TMDB results.
        db_title_keys = {
            (m.get("title", "").lower().strip(), m.get("year"))
            for m in docs
        }
        seed_to_add = [
            m for m in SEED_MOVIES
            if (m.get("title", "").lower().strip(), m.get("year")) not in db_title_keys
        ]
        CATALOG = docs + seed_to_add
    else:
        CATALOG = list(SEED_MOVIES)
    # Attach content cards (idempotent — only fills `card` if missing
    # OR when the on-disk schema_version is older than current)
    from content_cards import attach_cards
    # Snapshot themes that came from DB so we can detect which docs changed
    # and bulk-write only the deltas back to movies_cache (persistence
    # requirement for Task #8 — themes must live on each title doc, not
    # only in memory).
    _pre_themes = {m.get("id"): list(m.get("themes") or []) for m in CATALOG}
    attach_cards(CATALOG)
    db_count = len(docs) if docs else 0
    seed_count = len(CATALOG) - db_count
    logger.info(f"Catalog loaded: {len(CATALOG)} titles ({db_count} DB + {seed_count} seed)")

    # Persist newly-extracted themes back to Mongo so the field is available
    # to any future consumer of the raw movies_cache documents (admin tools,
    # downstream services, restarts before this code re-runs).  Only writes
    # docs whose themes actually changed — keeps the bulk_write small.
    if docs:
        from pymongo import UpdateOne
        ops = []
        for m in CATALOG:
            mid = m.get("id")
            if not mid or mid not in _pre_themes:
                continue  # seed-only entry, not in DB
            new_themes = list(m.get("themes") or [])
            if new_themes != _pre_themes[mid]:
                ops.append(UpdateOne({"id": mid}, {"$set": {"themes": new_themes}}))
        if ops:
            try:
                await db.movies_cache.bulk_write(ops, ordered=False)
                logger.info(f"Themes persisted to movies_cache: {len(ops)} docs updated")
            except Exception as e:
                logger.warning(f"Theme persistence had non-fatal errors: {type(e).__name__}")


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


def create_access_token(user_id: str, email: str, iat: Optional[int] = None) -> str:
    now = datetime.now(timezone.utc)
    issued_at = iat if iat is not None else int(now.timestamp())
    return jwt.encode(
        {"sub": user_id, "email": email, "type": "access",
         "iat": issued_at,
         "exp": now + timedelta(days=7)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str, iat: Optional[int] = None) -> str:
    now = datetime.now(timezone.utc)
    issued_at = iat if iat is not None else int(now.timestamp())
    return jwt.encode(
        {"sub": user_id, "type": "refresh",
         "iat": issued_at,
         "exp": now + timedelta(days=30)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*7, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=60*60*24*30, path="/")


def clean_user(doc: Optional[dict]) -> Optional[dict]:
    """Strip internal-only fields from a user document (used in request context)."""
    if not doc:
        return doc
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    doc.pop("apple_refresh_token", None)
    return doc


# Fields that are backend-only bookkeeping and must never be sent to the browser.
# recently_shown  — LRU list of up to 500 movie IDs used to prevent repeats
# onboarding_rated — movie IDs rated during the onboarding flow
_PUBLIC_STRIP = (
    "recently_shown",
    "onboarding_rated",
    "apple_sub",
    "apple_refresh_token",
)


def public_user(doc: Optional[dict]) -> Optional[dict]:
    """Like clean_user but also strips heavyweight backend-only fields.

    Use this for all API responses (register, login, /me, action, prefs).
    Do NOT use it for the user dict passed to route handlers — those handlers
    need recently_shown etc. for feed-building and cooldown logic.
    """
    doc = clean_user(doc)
    if not doc:
        return doc
    # Explicit, privacy-safe analytics exclusion marker. Mongo user documents
    # may be manually flagged by operators without exposing why an account is
    # internal/test or sending identifiers such as email to analytics clients.
    doc["analytics_internal"] = bool(doc.get("analytics_internal", False))
    for f in _PUBLIC_STRIP:
        doc.pop(f, None)
    return doc


async def resolve_user(request: Request) -> Optional[dict]:
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
        if not user:
            return None
        # Reject tokens minted before the user's last password change so
        # changing a password actually invalidates active sessions everywhere.
        pw_changed = user.get("password_changed_at")
        token_iat = payload.get("iat")
        if pw_changed and token_iat is not None and token_iat < pw_changed:
            return None
        return clean_user(user)
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
    dob: Optional[str] = None          # ISO date string "YYYY-MM-DD", optional
    gender: Optional[str] = None       # "male" | "female" | "nonbinary" | "prefer_not_to_say"
    accept_terms: Optional[bool] = None  # T&C + Privacy acceptance (stamped at signup)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


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
    dob: Optional[str] = None          # ISO date string "YYYY-MM-DD"
    gender: Optional[str] = None       # "male" | "female" | "nonbinary" | "prefer_not_to_say"
    show_international: Optional[bool] = None   # False = English-language titles only
    show_anime_asian: Optional[bool] = None     # True = opt back into anime + Asian-language drama (hidden by default)
    year_range: Optional[Literal["any", "last_10", "recent_only"]] = None
    # Discover toggles — persisted so opt-in survives logout / multi-device.
    include_other_services: Optional[bool] = None  # show titles outside subscriptions
    include_rent_buy: Optional[bool] = None        # show rent/buy alongside subscriptions
    # Per-service subscription plan selection (region GB / GBP). Keyed by
    # service_id → { plan_id, billing_cycle, effective_monthly_cost,
    # included_with_other_provider, custom_price, promo_ends? }. Persisted onto
    # the user doc as `subscription_plans` and used by /savings for accurate spend.
    subscription_plans: Optional[dict] = None
    # ISO timestamp stamped when the user finishes the app tutorial/onboarding
    # walkthrough. Surfaced back via /auth/me + preferences GET.
    tutorial_completed_at: Optional[str] = None


class ProgressIn(BaseModel):
    movie_id: str
    season: int = Field(ge=1, le=200)
    episode: int = Field(ge=1, le=999)


class EpisodeProgressIn(BaseModel):
    movie_id: str
    season: int = Field(ge=1, le=200)
    episode: int = Field(ge=1, le=999)
    watched: bool = True
    provenance: Literal["explicit", "inferred"] = "explicit"


class ReviewIn(BaseModel):
    movie_id: str
    rating: int = Field(ge=1, le=10)
    text: str = Field(min_length=1, max_length=2000)


class ActionIn(BaseModel):
    movie_id: str
    action: Literal["save", "skip", "watched", "unsave", "unwatched", "unskip"]
    impression_id: Optional[str] = None  # links action to specific recommendation


class EngageIn(BaseModel):
    movie_id: str
    action: str  # "detail_view" | "trailer_open" | "search_click"
    impression_id: Optional[str] = None  # links engagement to specific recommendation


class ExplainIn(BaseModel):
    movie_id: str


class ClickIn(BaseModel):
    movie_id: str
    service_id: str


# --- Recommendation engine -----------------------------------------------
# Action semantics (Task #7):
#   save               → strongest positive standalone signal
#   skip               → strong negative; negatives outweigh one-off positives
#   watched (neutral)  → "I've already seen this" — removes from feed,
#                        only weak/neutral preference signal
#   watched_liked      → watched a title the user had previously SAVED.
#                        Strongest possible positive signal.
#   watched_disliked   → watched a title the user had previously SKIPPED
#                        ("watched anyway and confirmed not for me"). Strongest
#                        negative signal.
# The composite "watched_liked" / "watched_disliked" values are resolved at
# write time in routers/user.py — the frontend still only sends save/skip/watched.
ACTION_WEIGHTS = {
    "save":             1.0,
    "skip":            -1.0,
    "watched":          0.2,   # plain watched alone — weak/neutral
    "watched_liked":    2.0,   # watched + previously saved → strongest +
    "watched_disliked": -2.0,  # watched + previously skipped → strongest −
}

# Languages considered Bollywood/South Asian cinema
_BOLLYWOOD_LANGS = {"hi", "te", "ta", "kn", "ml"}

# UK market default: original languages whose content UK users overwhelmingly
# reject (East/SE/South Asian drama). Anime is detected separately. These are
# hidden by default and only shown to users who opt in via show_anime_asian.
# Nothing is removed from the catalog — opted-in users receive this normally.
_ASIAN_DEFAULT_HIDE_LANGS = {
    "ja", "ko", "zh", "cn", "th", "id", "tl", "vi", "ms",
    "hi", "te", "ta", "kn", "ml",
}

# Family/Kids audience signals
_FAMILY_GENRES = {"Family", "Kids"}
_FAMILY_ANIMATION_CO_GENRES = {"Comedy", "Adventure", "Fantasy", "Music"}


def catalog_quality_gate(movie: dict, user_region: Optional[str] = None, user: "dict | None" = None) -> bool:
    """Return True if a title is eligible for Discover / recommendations.

    Excludes titles that users cannot actually watch:
      - Missing poster (no artwork)
      - Missing/empty overview
      - Explicit pre-release status (Rumored / Planned / In Production /
        Post Production / Pilot) when that field is populated
      - Movie with explicit runtime == 0 (placeholder / unreleased TMDB stub)
      - Junk records (rating < 4.0 AND vote_count < 5)
      - Future release date with no provider data (not out yet)
      - Enriched with zero providers AND below quality threshold
        (catches festival-only / limited-release / unavailable titles)

    Titles with unknown fields (None / missing) are given the benefit of the
    doubt — they may not yet be enriched.  These hard rejects always remain
    searchable; quality gate is only applied to Discover/Trending/Upcoming
    /Popular / engine ranking surfaces — never to /search.
    """
    if not movie.get("poster_url"):
        return False

    # Empty overview → unwatchable card. Older records may have non-empty
    # overview already; cast_backfill never clears it. Safe to enforce.
    overview = (movie.get("overview") or "").strip()
    if not overview:
        return False

    # Pre-release / unreleased status (only enforce when status is known)
    status = (movie.get("status") or "").strip()
    if status and status in {
        "Rumored", "Planned", "In Production", "Post Production", "Pilot",
    }:
        return False

    vote_count = int(movie.get("vote_count") or 0)
    rating     = float(movie.get("rating") or 0)

    # Movie runtime gate. An EXPLICIT non-positive runtime (0) marks a
    # placeholder / unreleased TMDB stub and is rejected. `runtime=None` means
    # the title simply has not been runtime-backfilled yet — give it the benefit
    # of the doubt (consistent with how this gate treats every other unknown
    # field) so genuinely watchable films are not silently dropped from Discover.
    # The poster/overview/status/junk/provider gates below still guarantee the
    # title is real and watchable.
    if movie.get("type") == "movie":
        rt = movie.get("runtime")
        if rt is not None and int(rt) <= 0:
            return False

    # Junk record floor — neither audience nor critical signal
    if vote_count < 5 and rating < 4.0:
        return False

    # Region-aware availability: resolve providers for the user's region so a
    # title enriched for GB doesn't count as watchable evidence for a US user
    # (and vice-versa) once region-keyed data exists.
    if user_region:
        _resolved = resolve_region_providers(movie, user_region)
        has_any_provider = bool(
            _resolved["available_on"] or _resolved["rent_on"] or _resolved["buy_on"]
        )
        region_matched = _resolved["region_matched"]
        # "Fetched" for THIS region: a region-keyed entry (always carries a
        # fetched_at) or legacy flat data that represents this region. A title
        # enriched on-demand for a non-default region sets only
        # providers_by_region.<REGION> (no global providers_fetched), so we must
        # trust the region-resolved timestamp — not the global flat flag.
        region_fetched = region_matched and bool(_resolved["fetched_at"])
    else:
        has_any_provider = (
            bool(movie.get("available_on")) or
            bool(movie.get("rent_on")) or
            bool(movie.get("buy_on"))
        )
        region_matched = True
        region_fetched = movie.get("providers_fetched") is True

    # ── Future-release gate ──────────────────────────────────────────────────
    # Use stored release_date when available (ISO string), else fall back to year.
    today = date.today().isoformat()
    release_date = movie.get("release_date") or ""
    current_year = date.today().year
    year = int(movie.get("year") or 0)

    is_future = (release_date and release_date > today) or (not release_date and year > current_year)

    if is_future and not has_any_provider:
        return False

    # ── Strict provider-data requirement ────────────────────────────────────
    # Discover requires confirmed provider data FOR THE USER'S REGION. Titles
    # never enriched for this region are excluded from Discover (they remain
    # searchable until enrichment runs). Region-keyed-only records qualify here
    # even without the global flat providers_fetched flag.
    if not region_fetched:
        return False

    # Title has been provider-enriched but has zero streaming/rental/buy
    # options — unwatchable, exclude from Discover.
    if not has_any_provider:
        return False

    # ── Region-mismatch gate ────────────────────────────────────────────────
    # Provider data is region-specific. If we have no trustworthy availability
    # data for the user's region (no region-keyed entry and the legacy flat
    # fields belong to a different region), that data is NOT valid evidence for
    # this user — reject. Re-enrichment for user_region is required to qualify.
    if user_region and not region_matched:
        return False

    # ── Release-year eligibility gate (hard) ───────────────────────────────
    # Default floor: 2005 for both movies and TV. Only apply to KNOWN valid
    # years — never reject for missing/unknown year. Classic exceptions let
    # genuinely strong older titles through (see _classic_exception_ok), with
    # relaxed thresholds for users who have shown clear classic affinity.
    year = int(movie.get("year") or 0)
    if year > 0 and year < RELEASE_YEAR_FLOOR:
        if not _classic_exception_ok(movie, user=user):
            return False

    return True


def _age_tier(movie: dict) -> Optional[str]:
    """Return A (2010+), B (2000–2009), C (pre-2000), or None for unknown year."""
    year = int(movie.get("year") or 0)
    if not year:
        return None
    if year >= 2010:
        return "A"
    if year >= 2000:
        return "B"
    return "C"


# Hard release-year floor for the normal Discover feed. Titles older than
# this only appear via the tiered classic exception below (strong evidence),
# with relaxed thresholds for users who have shown clear classic affinity.
RELEASE_YEAR_FLOOR = 2005


def user_has_classic_affinity(user: "dict | None") -> bool:
    """True when THIS user has clearly shown interest in classics/older titles.

    Signal is strictly per-user (never global learning): net positive decade
    weights for pre-2000s decades, accrued from the user's own saves/watches
    of older titles. A single accidental save is not enough — the net weight
    across classic decades must clear a threshold.
    """
    if not user:
        return False
    dw = user.get("decade_weights") or {}
    classic_net = 0.0
    for dec, w in dw.items():
        try:
            dec_year = int(str(dec).rstrip("s"))
        except (ValueError, TypeError):
            continue
        if dec_year < 2000:
            classic_net += float(w or 0)
    return classic_net >= 1.0


def _classic_exception_ok(movie: dict, user: "dict | None" = None) -> bool:
    """Strict tiered exception for pre-2005 titles to appear in Discover.

    Thresholds tighten with age. All tiers require poster, overview, English
    (unless user opted in to international), provider availability, and quality
    score when available. These are IN ADDITION to the upstream quality gate.
    Users with demonstrated classic affinity get relaxed (but still non-trivial)
    thresholds — the relaxation is per-user, never global.
    """
    year = int(movie.get("year") or 0)
    if not year or year >= RELEASE_YEAR_FLOOR:
        return False  # not a classic candidate

    # Must have poster + overview (already enforced by quality gate, but
    # re-check here so the exception is self-documenting).
    if not movie.get("poster_url"):
        return False
    if not (movie.get("overview") or "").strip():
        return False

    vote_count = int(movie.get("vote_count") or 0)
    rating     = float(movie.get("rating") or 0)
    popularity = float(movie.get("popularity") or 0)

    # ── Language gate (English unless user opted in) ──────────────────────
    lang = movie.get("original_language") or "en"
    if user and lang != "en":
        # User explicitly opted in to non-English content
        if user.get("show_international"):
            pass  # allowed
        else:
            # Check if user has positive signal for this specific language
            lw = user.get("language_weights") or {}
            if lw.get(lang, 0) <= 0:
                return False  # non-English without opt-in or positive signal
    elif not user and lang != "en":
        # Catalog-wide audit: require English or allow with show_anime_asian
        pass  # no strict language gate for catalog-wide checks (they lack user context)

    # ── Quality-score gate when available ─────────────────────────────────
    card = movie.get("card") or {}
    q_score = card.get("quality_score")
    if q_score is not None:
        q_score = int(q_score)
        # Classics must be at least Tier B quality (>=55 on 0-100 scale)
        if q_score < 55:
            return False

    # ── Tiered thresholds — stricter the older the title ──────────────────
    # Users with demonstrated classic affinity get one notch of relaxation
    # (rating -0.5, votes halved, popularity halved). This is strictly
    # per-user: no global signal can loosen these bars for everyone.
    _affinity = user_has_classic_affinity(user)

    def _tier(votes: int, rate: float, pop: float) -> bool:
        if _affinity:
            votes, rate, pop = votes // 2, rate - 0.5, pop / 2
        return vote_count >= votes and rating >= rate and popularity >= pop

    if year < 1960:
        # Pre-1960: exceptional only
        return _tier(2000, 8.5, 100)
    if year < 1980:
        # Pre-1980: very strong evidence required
        return _tier(1000, 8.0, 50)
    if year < 2000:
        # Pre-2000: solid evidence required
        return _tier(300, 7.5, 20)
    # 2000–2004: modern-classic band — must be genuinely good, not filler.
    # This is the band that previously had NO quality bar at all and let
    # weak titles (rating < 6) into every feed.
    return _tier(300, 7.0, 10)


def classic_admission_reason(movie: dict, user: "dict | None" = None) -> dict:
    """Structured audit record explaining WHY a pre-floor title is (in)eligible.

    Used by the feed audit logger so any old title appearing in a feed can be
    traced: which tier admitted it, whether classic affinity relaxed the bar,
    and the raw evidence values.
    """
    year = int(movie.get("year") or 0)
    if not year or year >= RELEASE_YEAR_FLOOR:
        return {"applicable": False, "reason_code": "modern_title"}
    eligible = _classic_exception_ok(movie, user=user)
    if year < 1960:
        tier = "pre_1960_exceptional"
    elif year < 1980:
        tier = "pre_1980_very_strong"
    elif year < 2000:
        tier = "pre_2000_solid"
    else:
        tier = "band_2000_2004_modern_classic"
    return {
        "applicable": True,
        "eligible": eligible,
        "reason_code": ("classic_exception_" + tier) if eligible else "rejected_" + tier,
        "tier": tier,
        "year": year,
        "rating": float(movie.get("rating") or 0),
        "vote_count": int(movie.get("vote_count") or 0),
        "popularity": float(movie.get("popularity") or 0),
        "quality_score": (movie.get("card") or {}).get("quality_score"),
        "classic_affinity": user_has_classic_affinity(user),
    }


def _is_family_kids(movie: dict) -> bool:
    """Return True if this title is family/kids content by any signal."""
    genres = set(movie.get("genres") or [])
    if genres & _FAMILY_GENRES:
        return True
    card = movie.get("card") or {}
    if card.get("audience_type") in ("kids", "family"):
        return True
    # Animation + typical family co-genres (Pixar / Disney-style)
    if "Animation" in genres and (genres & _FAMILY_ANIMATION_CO_GENRES):
        return True
    if "kids" in set(movie.get("tags") or []):
        return True
    return False


def _is_anime(movie: dict) -> bool:
    """Detect Japanese animation. Pixar/Disney/Western animation are NOT anime."""
    if "anime" in set(movie.get("tags") or []):
        return True
    genres = set(movie.get("genres") or [])
    if "Animation" in genres and movie.get("original_language") == "ja":
        return True
    return False


def _is_bollywood(movie: dict) -> bool:
    """Detect Bollywood/South Asian cinema by language or tag."""
    if "bollywood" in set(movie.get("tags") or []):
        return True
    if movie.get("original_language") in _BOLLYWOOD_LANGS:
        return True
    return False


def _hidden_by_uk_default(movie: dict, user: dict) -> bool:
    """UK Anglo-service default: anime + Asian-language drama are kept OUT of the
    mainstream pool unless the user explicitly opts in via show_anime_asian.

    Nothing is deleted from the catalog — opted-in users receive this content
    normally; everyone else gets a mainstream Anglo feed from the first card.
    """
    if user.get("show_anime_asian"):
        return False
    if _is_anime(movie) or _is_bollywood(movie):
        return True
    return (movie.get("original_language") or "en") in _ASIAN_DEFAULT_HIDE_LANGS


def movie_matches(movie: dict, user: dict) -> bool:
    """Strict match: quality gate + audience classification + subscription + content_type + excluded_genres.

    ORDER OF FILTERS (applied left to right, short-circuit on False):
      0. Catalog quality gate — exclude unreleased / unwatchable titles
      1. Family/Kids audience classification (if excluded) — runs FIRST, deal-breaker
         Comedy + Family stays out of adult Comedy. Action + Family stays out of adult Action.
      2. Anime exclusion (Japanese animation only; Pixar/Western stays)
      3. Bollywood exclusion (Hindi, Telugu, Tamil, Kannada, Malayalam)
      4. Subscription filter (opt-in: only when provider data exists)
      5. Content-type filter (movie / tv / both)
      6. Explicit excluded genres

    Subscription filter is a HARD REQUIREMENT when subscriptions are set.
    Titles with empty available_on are excluded — they are not on any subscription.
    Unenriched titles (providers_fetched=False, available_on=[]) are therefore also
    excluded when subscriptions are set; they re-enter once provider data is fetched.
    """
    # 0. Quality gate — unreleased / no watching option below quality bar.
    # Pass user region so titles whose providers were enriched for a
    # different region (with no provider hits) are excluded.
    _region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    if not catalog_quality_gate(movie, user_region=_region, user=user):
        return False

    excluded = set(user.get("excluded_categories") or [])

    # 1. Family/Kids — audience classification, not just a genre tag
    if ("family" in excluded or "kids" in excluded) and _is_family_kids(movie):
        return False

    # 2. Anime / Asian-language drama — hidden by default for the UK Anglo
    # service; surfaced only when the user opts in (show_anime_asian). This is
    # authoritative and subsumes the legacy per-category anime/bollywood excludes,
    # so an opted-in user is never blocked by stale excluded_categories values.
    if _hidden_by_uk_default(movie, user):
        return False

    # 4. Subscription filter — strict: only show titles on user's subscriptions.
    # Region-resolved: a title on Netflix GB is NOT counted for a US user unless
    # we hold US data showing it on their Netflix. Titles with no region
    # availability are excluded when subscriptions are set, keeping the feed clean.
    subs = set(user.get("subscriptions") or [])
    if subs:
        available = set(resolve_region_providers(movie, _region)["available_on"])
        if not (available & subs):
            return False

    # 5. Content type filter
    content_type = user.get("content_type")
    if content_type and content_type != "both":
        if movie.get("type") != content_type:
            return False

    # 6. Explicit excluded genres
    excluded_genres = set(user.get("excluded_genres") or [])
    if excluded_genres and (set(movie.get("genres") or []) & excluded_genres):
        return False

    # 7. Language filter — hard control, opt-in English-only mode
    if not user.get("show_international", True):
        if (movie.get("original_language") or "en") != "en":
            return False

    # 8. Year range filter — hard control
    _yr_range = user.get("year_range")
    if _yr_range and _yr_range != "any":
        _movie_year = movie.get("year") or 0
        if _movie_year:
            _now_yr = date.today().year
            if _yr_range == "recent_only" and _now_yr - _movie_year > 5:
                return False
            elif _yr_range == "last_10" and _now_yr - _movie_year > 10:
                return False

    # 9. Auto-blocked languages — built from repeated skips (≈10 skips threshold)
    _auto_blocked_langs = set(user.get("auto_blocked_languages") or [])
    if _auto_blocked_langs and (movie.get("original_language") or "en") in _auto_blocked_langs:
        return False

    # 10. Auto-blocked decades — built from repeated decade skips
    _auto_blocked_decades = set(user.get("auto_blocked_decades") or [])
    if _auto_blocked_decades:
        _my = movie.get("year") or 0
        _dec = f"{(_my // 10) * 10}s" if _my else "unknown"
        if _dec in _auto_blocked_decades:
            return False

    return True


def movie_matches_no_subs(movie: dict, user: dict) -> bool:
    """Like movie_matches but skips the subscription filter (step 4).

    Used by build_feed to expand a critically thin core-genre pool: when a user
    has selected Horror but their subscription (e.g. Netflix) only carries 19
    Horror titles, this lets us include Horror on other services rather than
    showing an empty feed.  All other filters still apply: quality gate,
    family/anime/bollywood classification, content type, excluded genres.
    """
    _region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    if not catalog_quality_gate(movie, user_region=_region, user=user):
        return False
    excluded = set(user.get("excluded_categories") or [])
    if ("family" in excluded or "kids" in excluded) and _is_family_kids(movie):
        return False
    if _hidden_by_uk_default(movie, user):
        return False
    # step 4 (subscription filter) intentionally omitted
    content_type = user.get("content_type")
    if content_type and content_type != "both":
        if movie.get("type") != content_type:
            return False
    excluded_genres = set(user.get("excluded_genres") or [])
    if excluded_genres and (set(movie.get("genres") or []) & excluded_genres):
        return False

    if not user.get("show_international", True):
        if (movie.get("original_language") or "en") != "en":
            return False

    _yr_range = user.get("year_range")
    if _yr_range and _yr_range != "any":
        _movie_year = movie.get("year") or 0
        if _movie_year:
            _now_yr = date.today().year
            if _yr_range == "recent_only" and _now_yr - _movie_year > 5:
                return False
            elif _yr_range == "last_10" and _now_yr - _movie_year > 10:
                return False

    _auto_blocked_langs = set(user.get("auto_blocked_languages") or [])
    if _auto_blocked_langs and (movie.get("original_language") or "en") in _auto_blocked_langs:
        return False

    _auto_blocked_decades = set(user.get("auto_blocked_decades") or [])
    if _auto_blocked_decades:
        _my = movie.get("year") or 0
        _dec = f"{(_my // 10) * 10}s" if _my else "unknown"
        if _dec in _auto_blocked_decades:
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


def movie_match_pct(movie: dict, user: dict) -> int:
    """Honest per-title taste-match percentage shown on the Discover card.

    Derived from *concrete* taste overlaps so the number means something:
      • genre fit vs the user's onboarding picks (the most reliable signal —
        we deliberately do NOT lean solely on ``genre_weights``, which can be
        sparse/unset for many users),
      • title quality (rating + vote support),
      • watchability on the user's own subscriptions,
      • cast and era affinity, plus a small recency nudge.

    Label-only: this never filters or re-ranks the pool. Anchored around a
    confident baseline (these are already recommended titles) and clamped to a
    believable, never-perfect [50, 99] range.
    """
    mg = set(movie.get("genres") or [])
    pts = 0.0

    # Genre fit — dominant signal (onboarding picks are reliable) -----------
    prefs = set(user.get("genres") or [])
    if prefs:
        overlap = len(mg & prefs)
        pts += (min(overlap, 2) * 9) if overlap else -6
    # Learned genre weights add a soft positive bonus when present ----------
    gw = user.get("genre_weights") or {}
    learned_pos = sum(1 for g in mg if gw.get(g, 0) > 0)
    pts += min(learned_pos, 2) * 3

    # Quality ---------------------------------------------------------------
    rating = float(movie.get("rating") or 0)
    if rating:
        pts += max(-6.0, min(9.0, (rating - 7.0) * 3.5))
    if (movie.get("vote_count") or 0) < 50:
        pts -= 3

    # Watchable on the user's services --------------------------------------
    if set(movie.get("available_on") or []) & set(user.get("subscriptions") or []):
        pts += 5

    # Cast affinity ---------------------------------------------------------
    cw = user.get("cast_weights") or {}
    if cw:
        from taste import person_key
        card = movie.get("card") or {}
        cast = [person_key(c) for c in (card.get("cast") or movie.get("cast_names") or [])][:3]
        if any(isinstance(_w := cw.get(c, 0), (int, float)) and _w > 0 for c in cast):
            pts += 4

    # Era affinity ----------------------------------------------------------
    yr = movie.get("year") or 0
    dw = user.get("decade_weights") or {}
    if dw and yr and dw.get(f"{(yr // 10) * 10}s", 0) > 0:
        pts += 3

    # Recency nudge ---------------------------------------------------------
    if yr and (datetime.now(timezone.utc).year - yr) <= 2:
        pts += 2

    # Deterministic ±3 jitter so equal-scoring titles aren't identical ------
    # (md5, not built-in hash(), which is per-process randomized → drifts on restart)
    seed = int(hashlib.md5(str(movie.get("id")).encode()).hexdigest(), 16)
    jitter = (seed % 7) - 3
    return int(max(50, min(99, round(68.0 + pts + jitter))))


# --- TMDB section cache (10-min TTL) -------------------------------------
_SECTION_CACHE: dict = {}
_SECTION_TTL = 600


async def cached_section(path: str, kind: str, region: str, pages: int = 1):
    key = (path, region)
    now = time.time()
    cached = _SECTION_CACHE.get(key)
    if cached and (now - cached[0]) < _SECTION_TTL:
        return cached[1]
    try:
        items = await tmdb_client.fetch_endpoint(path, kind, pages=pages, region=region)
    except Exception as e:
        logger.warning(f"TMDB section {path} failed (no token or network error): {e}")
        return []
    # Attach content cards so all surfaces (discover/trending/upcoming/popular)
    # expose the same tone/audience/pacing/themes/confidence_score signals.
    from content_cards import attach_cards
    attach_cards(items)
    _SECTION_CACHE[key] = (now, items)
    return items


def apply_user_filters(items: list, user: dict, filter_subs: bool = True) -> list:
    """Applied to TMDB section results (trending/upcoming/popular/search).

    Strict filters run on every surface — Discover, Trending, Upcoming, Popular,
    Onboarding taste-check, Similar.
    Family/Kids, Anime, Bollywood, content_type, excluded_genres, and (when
    filter_subs=True) subscriptions all apply here.

    Pass filter_subs=False for the /search endpoint so all titles appear in
    results (they are labelled client-side instead of being removed).

    Two opt-in flags on the user dict relax subscription filtering and stay
    consistent with /discover (set by the section endpoints' _effective_user):
      _relax_subs        — drop subscription filter entirely
      _include_rent_buy  — also accept titles available to rent or buy
    """
    excluded = set(user.get("excluded_categories") or [])
    excluded_genres = set(user.get("excluded_genres") or [])
    content_type = user.get("content_type")
    family_excluded = "family" in excluded or "kids" in excluded
    subs = set(user.get("subscriptions") or []) if filter_subs else set()
    relax_subs = bool(user.get("_relax_subs"))
    include_rent_buy = bool(user.get("_include_rent_buy"))
    _region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()

    out = []
    for m in items:
        if family_excluded and _is_family_kids(m):
            continue
        if "anime" in excluded and _is_anime(m):
            continue
        if "bollywood" in excluded and _is_bollywood(m):
            continue
        if excluded_genres and (set(m.get("genres") or []) & excluded_genres):
            continue
        if content_type and content_type != "both" and m.get("type") != content_type:
            continue
        if subs and not relax_subs:
            _res = resolve_region_providers(m, _region)
            available = set(_res["available_on"])
            matched = bool(available & subs)
            if not matched and include_rent_buy:
                # Accept the title if the user owns ANY subscription and it is
                # rentable/buyable in their region — keeps strict-mode-by-default
                # but opens the catalog when the user opts in.
                matched = bool(_res["rent_on"]) or bool(_res["buy_on"])
            if not matched:
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
    "db", "JWT_SECRET", "JWT_ALGORITHM",
    "logger", "tmdb_client",
    "load_catalog_from_db", "refresh_catalog_from_tmdb", "get_catalog",
    "movies_by_ids", "find_movie", "CATALOG",
    "hash_password", "verify_password", "create_access_token", "create_refresh_token",
    "set_auth_cookies", "clean_user", "public_user", "resolve_user", "require_user", "require_admin",
    "RegisterIn", "LoginIn", "ChangePasswordIn", "PreferencesIn", "ProgressIn", "ReviewIn", "ActionIn", "ExplainIn", "ClickIn",
    "ACTION_WEIGHTS", "movie_matches", "movie_matches_no_subs", "movie_score", "movie_reason", "movie_match_pct",
    "cached_section", "apply_user_filters", "seed_notifications_for_user",
    "SEED_MOVIES", "STREAMING_SERVICES", "GENRES",
    "httpx", "uuid", "datetime", "timezone", "timedelta",
]
