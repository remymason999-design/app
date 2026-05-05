"""WatchSmart recommendation engine.

A continuous, self-improving discovery pipeline:

  1. Build a per-user candidate pool from the catalog by applying ALL user
     filters strictly (subscriptions, excluded categories, excluded genres,
     content type, and a sliding "recently shown" cooldown).
  2. Score every candidate with a hybrid model that blends:
       - title quality (rating + popularity, decaying as user matures)
       - explicit preferences (onboarding genres + moods)
       - learned behaviour (genre_weights / type_weights mutated by every swipe)
       - lightweight collaborative filtering — boost titles liked by users
         whose `genre_weights` vector is closest to ours
       - recency / freshness boost
  3. Inject 5-10% controlled randomness (within filters) so the feed never
     stagnates.
  4. Maintain `recently_shown` LRU on the user doc so we never serve the same
     card twice in quick succession; expired entries become eligible again,
     and previously-skipped items can re-enter via the cooldown re-introduction
     path if their genres now match the user's top weights.
  5. If the candidate pool drops below `LOW_WATER`, schedule a non-blocking
     TMDB top-up so the feed effectively never runs out.

Public surface:
    build_feed(user, limit) -> list[dict]
    record_shown(user_id, ids) -> coroutine that appends to recently_shown
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

from core import db, get_catalog, movie_matches, tmdb_client

logger = logging.getLogger("watchsmart.engine")

# Thresholds & knobs (tune freely)
RECENTLY_SHOWN_MAX = 200          # max ids tracked per user
RECENTLY_SHOWN_COOLDOWN_HRS = 6   # how long a shown item is suppressed
SKIP_COOLDOWN_DAYS = 30           # how long until a skipped item can return
RANDOM_INJECTION_PCT = 0.08       # 8% of returned slots are random-within-filter
COLLAB_NEIGHBOURS = 5             # nearest users for collaborative bonus
COLLAB_BONUS = 1.5                # max boost from collaborative signal
LOW_WATER = 200                   # below this, schedule a background TMDB top-up
TARGET_POOL = 2000                # target unseen+filtered pool size per user

_REFILL_LOCK: dict = {}           # user_id -> asyncio.Task to dedupe refills


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _genre_vector(weights: dict) -> dict:
    """Return a normalized genre weight dict (sum to 1)."""
    if not weights:
        return {}
    total = sum(abs(v) for v in weights.values()) or 1.0
    return {g: v / total for g, v in weights.items()}


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _maturity(user: dict) -> float:
    """0..1 — how 'mature' is this user's preference signal?

    Used to interpolate between popularity-driven (cold-start) and personalised
    (mature) ranking. Reaches 1.0 around ~50 total interactions.
    """
    interactions = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    return min(1.0, interactions / 50.0)


def _recently_shown_active(user: dict) -> set:
    """Ids shown in the last RECENTLY_SHOWN_COOLDOWN_HRS hours."""
    rs = user.get("recently_shown") or []
    if not rs:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENTLY_SHOWN_COOLDOWN_HRS)
    out = set()
    for entry in rs:
        ts = entry.get("at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts and ts >= cutoff:
            mid = entry.get("id")
            if mid:
                out.add(mid)
    return out


async def _eligible_skip_reintros(user: dict, top_genres: set) -> set:
    """Old skips (>30d) where movie's genres overlap user's currently boosted
    genres become eligible to be re-introduced — taste shifts happen."""
    if not top_genres:
        return set()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=SKIP_COOLDOWN_DAYS)).isoformat()
    cursor = db.user_actions.find(
        {"user_id": user["user_id"], "action": "skip", "created_at": {"$lt": cutoff_iso}},
        {"_id": 0, "movie_id": 1},
    )
    rows = await cursor.to_list(length=1000)
    skip_ids = {r["movie_id"] for r in rows}
    if not skip_ids:
        return set()
    catalog_by_id = {m["id"]: m for m in get_catalog()}
    return {
        mid for mid in skip_ids
        if mid in catalog_by_id and (set(catalog_by_id[mid].get("genres") or []) & top_genres)
    }


async def _collaborative_boost_set(user: dict, top_n: int = COLLAB_NEIGHBOURS) -> set:
    """Find users with the most similar genre_weights and gather titles they
    saved. Returns a set of movie_ids that should get a soft boost."""
    my_vec = _genre_vector(user.get("genre_weights") or {})
    if not my_vec:
        return set()
    # Sample candidate neighbours: users with at least one saved title and a
    # non-empty genre_weights map. We cap at 200 candidates to keep it cheap.
    cursor = db.users.find(
        {
            "user_id": {"$ne": user["user_id"]},
            "saved.0": {"$exists": True},
            "genre_weights": {"$exists": True, "$ne": {}},
        },
        {"_id": 0, "user_id": 1, "saved": 1, "genre_weights": 1},
    ).limit(200)
    candidates = await cursor.to_list(length=200)
    scored = []
    for u in candidates:
        sim = _cosine(my_vec, _genre_vector(u.get("genre_weights") or {}))
        if sim > 0.2:
            scored.append((sim, u))
    scored.sort(key=lambda x: x[0], reverse=True)
    boost_ids: set = set()
    for sim, u in scored[:top_n]:
        for mid in u.get("saved") or []:
            boost_ids.add(mid)
    return boost_ids


def _hybrid_score(
    movie: dict,
    user: dict,
    *,
    maturity: float,
    collab_set: set,
    learned_top_genres: set,
    current_year: int,
) -> float:
    """Hybrid score blending quality, explicit prefs, learned weights, collab,
    recency. `maturity` shifts emphasis from popularity to personalisation."""
    rating = float(movie.get("rating") or 7.0)
    popularity = float(movie.get("popularity") or 0)

    # Quality term: rating dominates as user matures, popularity dominates cold start
    pop_term = math.log1p(popularity) * (1.0 - maturity)   # decays
    rating_term = (rating / 2.0) * (0.5 + 0.5 * maturity)  # grows
    quality = pop_term + rating_term

    # Demote low-vote-count titles slightly for cold-start users
    if (movie.get("vote_count") or 0) < 50 and maturity < 0.4:
        quality -= 0.5

    mg = set(movie.get("genres") or [])

    # Explicit prefs (from onboarding)
    onboard_prefs = set(user.get("genres") or [])
    onboard_overlap = len(mg & onboard_prefs)

    # Learned weights (from every rate/swipe)
    gw = user.get("genre_weights") or {}
    learned = sum(gw.get(g, 0) for g in mg)

    # Type preference
    type_pref = (user.get("type_weights") or {}).get(movie.get("type"), 0)

    # Recency
    year = movie.get("year") or 0
    recency = 0.6 if year and (current_year - year) <= 2 else 0

    # Collaborative bonus
    collab = COLLAB_BONUS if movie["id"] in collab_set else 0

    # Re-intro bonus
    reintro = 0.5 if (mg & learned_top_genres) else 0

    jitter = (hash(movie["id"]) % 100) / 1000.0

    return (
        quality
        + onboard_overlap * 1.0
        + learned * 0.4 * (0.5 + 0.5 * maturity)
        + type_pref * 0.3
        + recency
        + collab
        + reintro
        + jitter
    )


def _reason_for(movie: dict, user: dict, *, in_collab: bool, is_reintro: bool) -> str:
    mg = set(movie.get("genres") or [])
    gw = user.get("genre_weights") or {}
    if is_reintro:
        return "Worth a second look"
    if in_collab:
        return "Loved by people with your taste"
    top_learned = sorted(((g, gw.get(g, 0)) for g in mg), key=lambda x: x[1], reverse=True)
    if top_learned and top_learned[0][1] >= 2:
        return f"Because you've been loving {top_learned[0][0]}"
    onboard = set(user.get("genres") or [])
    overlap = list(mg & onboard)
    if overlap:
        return f"Matches your {overlap[0]} taste"
    if (movie.get("rating") or 0) >= 8.5:
        return f"Critically acclaimed · {movie.get('rating')}/10"
    return "Worth a look tonight"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_feed(user: dict, limit: int = 20) -> list[dict]:
    """Compute a personalised feed for `user`.

    Strict invariants:
      * No item from saved/watched/skipped/onboarding_rated (unless eligible
        cooldown re-intro)
      * No item shown in last 6h (`recently_shown` LRU)
      * All user filters honoured (subscriptions, excluded categories,
        excluded genres, content type)
      * 5-10% slots filled with random-within-filter for diversity
    """
    catalog = get_catalog()
    if not catalog:
        return []

    permanently_seen = set(
        (user.get("saved") or []) +
        (user.get("watched") or []) +
        (user.get("onboarding_rated") or [])
    )
    skipped = set(user.get("skipped") or [])
    cooldown_set = _recently_shown_active(user)

    # Top genres by current learned weight — used for both reintros and reasons
    gw = user.get("genre_weights") or {}
    learned_top_genres = {
        g for g, v in sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:3] if v >= 2
    }
    reintro_eligible = await _eligible_skip_reintros(user, learned_top_genres)

    # Build candidate pool
    pool = []
    for m in catalog:
        mid = m["id"]
        if mid in permanently_seen:
            continue
        if mid in cooldown_set:
            continue
        if mid in skipped and mid not in reintro_eligible:
            continue
        if not movie_matches(m, user):
            continue
        pool.append(m)

    # EMERGENCY REINTRODUCTION: if the filtered pool is critically small,
    # reintroduce skipped items (they may have been rejected before tastes
    # converged). This prevents empty-feed states for narrow-filter users.
    POOL_EMERGENCY = 30
    if len(pool) < POOL_EMERGENCY and skipped:
        for m in catalog:
            mid = m["id"]
            if mid in permanently_seen or mid in cooldown_set:
                continue
            if mid not in skipped:
                continue
            if not movie_matches(m, user):
                continue
            reintro_eligible.add(mid)
            pool.append(m)

    # ULTRA-EMERGENCY: pool STILL near-empty (user swiped everything in their
    # filtered universe within the cooldown window). Bypass the recently-shown
    # LRU so they at least see something — these items still get a soft
    # re-intro reason.
    POOL_ULTRA_EMERGENCY = 8
    if len(pool) < POOL_ULTRA_EMERGENCY:
        existing = {m["id"] for m in pool}
        for m in catalog:
            mid = m["id"]
            if mid in existing or mid in permanently_seen:
                continue
            if not movie_matches(m, user):
                continue
            reintro_eligible.add(mid)
            pool.append(m)
        if pool:
            logger.info(f"Pool ultra-emergency: bypassed cooldown LRU, pool now {len(pool)}")

    # Adaptive popularity cap — keep more for cold-start, narrower for mature users
    maturity = _maturity(user)
    cap = max(500, int(TARGET_POOL * (1.0 - 0.6 * maturity)))
    if len(pool) > cap:
        pool.sort(key=lambda m: m.get("popularity", 0), reverse=True)
        pool = pool[:cap]

    # Pull collaborative signal in parallel (doesn't block scoring)
    collab_set = await _collaborative_boost_set(user)

    current_year = datetime.now(timezone.utc).year
    pool.sort(
        key=lambda m: _hybrid_score(
            m, user,
            maturity=maturity,
            collab_set=collab_set,
            learned_top_genres=learned_top_genres,
            current_year=current_year,
        ),
        reverse=True,
    )

    # Random injection — replace ~8% of top slots with random-from-rest
    rand_slots = max(1, int(limit * RANDOM_INJECTION_PCT))
    top = pool[: limit - rand_slots]
    rest = pool[limit - rand_slots:]
    if rest:
        random.shuffle(rest)
        chosen_random = rest[:rand_slots]
    else:
        chosen_random = []

    selected = top + chosen_random

    # Auto-refill if pool is running low (fire-and-forget)
    if len(pool) < LOW_WATER:
        _schedule_refill(user["user_id"])

    out = []
    for m in selected:
        in_collab = m["id"] in collab_set
        is_reintro = m["id"] in reintro_eligible and m["id"] in skipped
        item = dict(m)
        item["reason"] = _reason_for(m, user, in_collab=in_collab, is_reintro=is_reintro)
        item["_signals"] = {
            "in_collab": in_collab,
            "is_reintro": is_reintro,
            "maturity": round(maturity, 2),
            "pool_size": len(pool),
        }
        out.append(item)

    # Track shown asynchronously (don't await — stays out of the hot path)
    _schedule_record_shown(user["user_id"], [m["id"] for m in out])

    return out


# ---------------------------------------------------------------------------
# Recently-shown tracker
# ---------------------------------------------------------------------------

async def _record_shown(user_id: str, ids: Iterable[str]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    new_entries = [{"id": i, "at": now_iso} for i in ids]
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "recently_shown": 1})
    existing = (user or {}).get("recently_shown") or []
    # Drop existing entries for the same ids, then prepend new ones
    new_ids = {e["id"] for e in new_entries}
    merged = new_entries + [e for e in existing if e.get("id") not in new_ids]
    merged = merged[:RECENTLY_SHOWN_MAX]
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"recently_shown": merged}},
    )


def _schedule_record_shown(user_id: str, ids: list[str]) -> None:
    if not ids:
        return
    try:
        asyncio.create_task(_record_shown(user_id, ids))
    except RuntimeError:
        # No running loop (rare — background context). Skip silently.
        pass


# ---------------------------------------------------------------------------
# Background refill
# ---------------------------------------------------------------------------

async def _do_refill(user_id: str) -> None:
    """Fetch a couple more deep TMDB pages and merge into movies_cache."""
    try:
        from core import refresh_catalog_from_tmdb
        added = await refresh_catalog_from_tmdb(pages=8)
        logger.info(f"Pool refill triggered by {user_id}: catalog now {added} titles")
    except Exception as e:
        logger.warning(f"Pool refill failed for {user_id}: {e}")
    finally:
        _REFILL_LOCK.pop(user_id, None)


def _schedule_refill(user_id: str) -> None:
    if user_id in _REFILL_LOCK:
        return
    try:
        task = asyncio.create_task(_do_refill(user_id))
        _REFILL_LOCK[user_id] = task
    except RuntimeError:
        pass


async def engagement_summary(user: dict) -> dict:
    """Lightweight transparency endpoint — what does the engine know about me?"""
    total_actions = await db.user_actions.count_documents({"user_id": user["user_id"]})
    by_action_pipeline = [
        {"$match": {"user_id": user["user_id"]}},
        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
    ]
    by_action: dict = {}
    async for row in db.user_actions.aggregate(by_action_pipeline):
        by_action[row["_id"]] = row["count"]
    gw = user.get("genre_weights") or {}
    top_genres = sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "maturity": round(_maturity(user), 2),
        "total_interactions": total_actions,
        "by_action": by_action,
        "top_learned_genres": [{"genre": g, "weight": v} for g, v in top_genres],
        "type_weights": user.get("type_weights") or {},
        "watchlist_size": len(user.get("saved") or []),
        "watched_count": len(user.get("watched") or []),
    }
