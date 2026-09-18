"""Admin router."""
import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from core import (
    db, require_admin, get_catalog, refresh_catalog_from_tmdb,
    load_catalog_from_db, logger, catalog_quality_gate, _age_tier,
    _classic_exception_ok, public_user,
)
from providers_util import resolve_region_providers
from catalog_import import bulk_import_catalog, enrich_providers_top
from pydantic import BaseModel, Field
from typing import Literal
from plus_launch import (
    delivery_metrics,
    dispatch_channel,
    launch_state,
    set_launch_approval,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _build_impression_conversion_report(
    impression_docs: list[dict],
    action_docs: list[dict],
    quality_tiers: dict,
) -> dict:
    """Attribute the first linked swipe outcome to each served card.

    Kept as a pure helper so the analytics rules can be tested without a
    database. Identity, movie id, impression id, and chronology must all match.
    """
    def timestamp(value) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value or "")

    served: dict[tuple, dict] = {}
    for feed in impression_docs:
        uid = feed.get("user_id")
        iid = feed.get("impression_id")
        feed_at = feed.get("at") or ""
        if not uid or not iid:
            continue
        for item in feed.get("items") or []:
            mid = item.get("id")
            if mid is None:
                continue
            key = (uid, iid, mid)
            served.setdefault(key, {
                "reason_code": item.get("reason_code") or "unknown",
                "slot": item.get("slot") or "unknown",
                "quality_tier": quality_tiers.get(mid, "unknown"),
                "served_at": timestamp(item.get("served_at") or feed_at),
                "outcome": None,
            })

    for action in sorted(action_docs, key=lambda row: timestamp(row.get("created_at"))):
        outcome = action.get("action")
        if outcome not in {"save", "skip", "watched"}:
            continue
        key = (action.get("user_id"), action.get("impression_id"), action.get("movie_id"))
        card = served.get(key)
        if (
            not card
            or card["outcome"] is not None
            or timestamp(action.get("created_at")) < card["served_at"]
        ):
            continue
        card["outcome"] = outcome

    def group(dimension: str) -> list[dict]:
        buckets = defaultdict(lambda: {
            "impressions": 0, "saves": 0, "skips": 0, "watched": 0,
        })
        for card in served.values():
            bucket = buckets[card[dimension]]
            bucket["impressions"] += 1
            if card["outcome"] == "save":
                bucket["saves"] += 1
            elif card["outcome"] == "skip":
                bucket["skips"] += 1
            elif card["outcome"] == "watched":
                bucket["watched"] += 1
        rows = []
        for value, counts in buckets.items():
            total = counts["impressions"]
            positive = counts["saves"] + counts["watched"]
            rows.append({
                "value": value,
                **counts,
                "responded": positive + counts["skips"],
                "save_rate_pct": round(counts["saves"] * 100 / total, 1),
                "positive_rate_pct": round(positive * 100 / total, 1),
                "skip_rate_pct": round(counts["skips"] * 100 / total, 1),
            })
        return sorted(rows, key=lambda row: (-row["impressions"], str(row["value"])))

    total = len(served)
    responded = sum(1 for card in served.values() if card["outcome"])
    return {
        "summary": {
            "impressions": total,
            "responded": responded,
            "response_rate_pct": round(responded * 100 / total, 1) if total else None,
        },
        "by_reason_code": group("reason_code"),
        "by_slot": group("slot"),
        "by_quality_tier": group("quality_tier"),
    }


class PlusLaunchApprovalIn(BaseModel):
    approved: bool


class PlusLaunchDispatchIn(BaseModel):
    channel: Literal["email", "push"]
    limit: int = Field(default=100, ge=1, le=500)


@router.get("/plus-launch")
async def admin_plus_launch_status(user: dict = Depends(require_admin)):
    return {"state": await launch_state(), "metrics": await delivery_metrics()}


@router.put("/plus-launch/approval")
async def admin_plus_launch_approval(
    payload: PlusLaunchApprovalIn,
    user: dict = Depends(require_admin),
):
    state = await set_launch_approval(
        approved=payload.approved,
        admin_user_id=user["user_id"],
    )
    return {"state": state}


@router.post("/plus-launch/dispatch")
async def admin_plus_launch_dispatch(
    payload: PlusLaunchDispatchIn,
    user: dict = Depends(require_admin),
):
    try:
        return await dispatch_channel(payload.channel, payload.limit)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/refresh-catalog")
async def admin_refresh_catalog(user: dict = Depends(require_admin), pages: int = 8):
    try:
        fetched = await refresh_catalog_from_tmdb(pages=pages)
        total = len(get_catalog())
        return {"ok": True, "count": total, "items_fetched": fetched, "catalog_total": total}
    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        raise HTTPException(502, f"TMDB refresh failed: {e}")


@router.post("/bulk-import")
async def admin_bulk_import(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
    pages_general: int = 10,
    pages_genre: int = 5,
    pages_provider: int = 3,
    region: str = "GB",
):
    """Trigger the full genre-balanced catalog import.

    Uses 11 general endpoints (popular/trending/top-rated) PLUS 102 genre-specific
    discover endpoints (18 movie genres × 3 sorts + 16 TV genres × 3 sorts) so
    every spec genre gets its own dedicated harvest slice.

    Defaults (pages_general=10, pages_genre=5):
      ~620 HTTP requests → ~12,000 raw items → ~6,000–10,000 unique titles
    Runs in the background — returns immediately.
    """
    from catalog_import import GENERAL_ENDPOINTS, GENRE_ENDPOINTS, PROVIDER_ENDPOINTS

    async def _run():
        try:
            result = await bulk_import_catalog(
                db,
                pages_general=pages_general,
                pages_genre=pages_genre,
                pages_provider=pages_provider,
            )
            await load_catalog_from_db()
            enriched = await enrich_providers_top(db, limit=1000, region=region)
            await load_catalog_from_db()
            logger.info(
                f"Admin bulk-import complete: {result['unique']} unique imported, "
                f"{enriched} providers enriched, {len(get_catalog())} in memory. "
                f"Genre coverage: {result.get('genre_coverage', {})}"
            )
        except Exception as exc:
            logger.error(f"Admin bulk-import failed: {exc}", exc_info=True)

    background_tasks.add_task(_run)
    db_count = await db.movies_cache.count_documents({})
    total_reqs = (
        len(GENERAL_ENDPOINTS) * pages_general
        + len(GENRE_ENDPOINTS) * pages_genre
        + len(PROVIDER_ENDPOINTS) * pages_provider
    )
    return {
        "ok": True,
        "message": (
            f"Genre+provider-balanced import started in background "
            f"(pages_general={pages_general}, pages_genre={pages_genre}, "
            f"pages_provider={pages_provider}, ~{total_reqs} HTTP requests)"
        ),
        "endpoints": {
            "general":         len(GENERAL_ENDPOINTS),
            "genre_specific":  len(GENRE_ENDPOINTS),
            "provider_region": len(PROVIDER_ENDPOINTS),
        },
        "current_db_count": db_count,
        "current_memory_catalog": len(get_catalog()),
    }


@router.post("/enrich-providers")
async def admin_enrich_providers(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
    limit: int = 500,
    region: str = "GB",
):
    """Fetch streaming provider data for top-N un-enriched titles by popularity."""
    un_enriched = await db.movies_cache.count_documents({"providers_fetched": {"$ne": True}})

    async def _run():
        try:
            enriched = await enrich_providers_top(db, limit=limit, region=region)
            await load_catalog_from_db()
            logger.info(f"Admin enrich-providers done: {enriched} titles updated")
        except Exception as e:
            logger.error(f"Admin enrich-providers failed: {e}", exc_info=True)
    background_tasks.add_task(_run)
    return {
        "ok": True,
        "message": f"Provider enrichment started for up to {limit} titles",
        "un_enriched_in_db": un_enriched,
    }


@router.get("/catalog-stats")
async def admin_catalog_stats(user: dict = Depends(require_admin)):
    """Detailed catalog health report including per-genre coverage."""
    from collections import Counter

    total_in_db = await db.movies_cache.count_documents({})

    # Run independent counts in parallel
    (
        with_poster, with_providers, un_enriched,
        movies_count, tv_count, high_rated, popular,
    ) = await asyncio.gather(
        db.movies_cache.count_documents({"poster_url": {"$exists": True, "$ne": None}}),
        db.movies_cache.count_documents({"providers_fetched": True}),
        db.movies_cache.count_documents({"providers_fetched": {"$ne": True}}),
        db.movies_cache.count_documents({"type": "movie"}),
        db.movies_cache.count_documents({"type": "tv"}),
        db.movies_cache.count_documents({"rating": {"$gte": 7.5}}),
        db.movies_cache.count_documents({"popularity": {"$gte": 20}}),
    )

    # Service counts in parallel — cover EVERY known service id (incl. UK-only
    # ITVX/NOW/Channel 4/discovery+/BBC iPlayer/MUBI) so import verification
    # reflects the full catalogue, not just the original US/global set.
    services = ["netflix", "disney_plus", "hbo_max", "prime_video",
                "apple_tv", "hulu", "paramount", "peacock",
                "itvx", "now_tv", "channel_4", "discovery_plus",
                "bbc_iplayer", "mubi"]
    svc_counts = await asyncio.gather(
        *[db.movies_cache.count_documents({"available_on": s}) for s in services]
    )
    by_service = dict(zip(services, svc_counts))

    # Genre coverage via aggregation (single pass)
    spec_genres = [
        "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary",
        "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery",
        "Romance", "Sci-Fi", "Thriller", "War", "Western",
    ]
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
    ]
    genre_coverage: dict[str, int] = {}
    async for row in db.movies_cache.aggregate(pipeline):
        genre_coverage[row["_id"]] = row["count"]

    genre_report = {
        g: {
            "count": genre_coverage.get(g, 0),
            "status": (
                "good"    if genre_coverage.get(g, 0) >= 200 else
                "ok"      if genre_coverage.get(g, 0) >= 50  else
                "low"
            ),
        }
        for g in spec_genres
    }

    return {
        "in_memory_catalog": len(get_catalog()),
        "db": {
            "total":             total_in_db,
            "with_poster":       with_poster,
            "providers_enriched": with_providers,
            "providers_pending": un_enriched,
            "movies":            movies_count,
            "tv_shows":          tv_count,
            "high_rated_gte_7_5": high_rated,
            "popular_gte_20":    popular,
        },
        "by_service": by_service,
        "genre_coverage": genre_report,
        "genre_summary": {
            "good_gte_200": sum(1 for v in genre_report.values() if v["status"] == "good"),
            "ok_50_199":    sum(1 for v in genre_report.values() if v["status"] == "ok"),
            "low_lt_50":    sum(1 for v in genre_report.values() if v["status"] == "low"),
        },
    }


@router.get("/debug-pool")
async def debug_pool(user: dict = Depends(require_admin)):
    """Show detailed filter-stage breakdown for the requesting user's Discover pool."""
    from core import get_catalog, _is_family_kids, _is_anime, _is_bollywood, movie_matches
    from engine import _recently_shown_active, _maturity

    catalog = get_catalog()
    excluded = set(user.get("excluded_categories") or [])
    family_excluded = "family" in excluded or "kids" in excluded

    total = len(catalog)
    after_family = after_anime = after_bollywood = after_subs = after_content_type = after_genres = 0

    permanently_seen = set(
        (user.get("saved") or []) +
        (user.get("watched") or []) +
        (user.get("onboarding_rated") or []) +
        (user.get("skipped") or [])
    )
    cooldown_set = _recently_shown_active(user)

    pre_filter_pool = [m for m in catalog if m["id"] not in permanently_seen and m["id"] not in cooldown_set]

    stage = list(pre_filter_pool)
    after_seen = len(stage)

    if family_excluded:
        stage = [m for m in stage if not _is_family_kids(m)]
    after_family = len(stage)

    if "anime" in excluded:
        stage = [m for m in stage if not _is_anime(m)]
    after_anime = len(stage)

    if "bollywood" in excluded:
        stage = [m for m in stage if not _is_bollywood(m)]
    after_bollywood = len(stage)

    subs = set(user.get("subscriptions") or [])
    if subs:
        stage = [m for m in stage if not (set(m.get("available_on") or []) and not (set(m.get("available_on") or []) & subs))]
    after_subs = len(stage)

    ct = user.get("content_type")
    if ct and ct != "both":
        stage = [m for m in stage if m.get("type") == ct]
    after_content_type = len(stage)

    ex_genres = set(user.get("excluded_genres") or [])
    if ex_genres:
        stage = [m for m in stage if not (set(m.get("genres") or []) & ex_genres)]
    after_genres = len(stage)

    gw = user.get("genre_weights") or {}
    top_genres = sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "catalog_total": total,
        "after_removing_seen_skipped": after_seen,
        "after_family_kids_filter": after_family,
        "after_anime_filter": after_anime,
        "after_bollywood_filter": after_bollywood,
        "after_subscription_filter": after_subs,
        "after_content_type_filter": after_content_type,
        "after_excluded_genres_filter": after_genres,
        "final_discover_pool": after_genres,
        "maturity": round(_maturity(user), 2),
        "top_learned_genres": [{"genre": g, "weight": round(w, 2)} for g, w in top_genres],
        "active_filters": {
            "family_kids_excluded": family_excluded,
            "anime_excluded": "anime" in excluded,
            "bollywood_excluded": "bollywood" in excluded,
            "subscriptions": list(subs),
            "content_type": ct or "both",
            "excluded_genres": list(ex_genres),
        },
    }


@router.get("/lookup")
async def admin_lookup_user(email: str, user: dict = Depends(require_admin)):
    """Lookup a single user by email — full taste/subscription/activity dump."""
    email_n = (email or "").lower().strip()
    if not email_n:
        raise HTTPException(400, "email is required")
    doc = await db.users.find_one(
        {"email": email_n},
        {"_id": 0, "password_hash": 0},
    )
    if not doc:
        raise HTTPException(404, "User not found")
    doc = public_user(doc)
    uid = doc["user_id"]
    action_count = await db.user_actions.count_documents({"user_id": uid})
    recent_actions = []
    async for a in db.user_actions.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).limit(25):
        recent_actions.append(a)
    return {
        "user": doc,
        "action_count": action_count,
        "recent_actions": recent_actions,
        "saved_count": len(doc.get("saved") or []),
        "watched_count": len(doc.get("watched") or []),
        "skipped_count": len(doc.get("skipped") or []),
    }


@router.get("/recommendation-debug")
async def admin_recommendation_debug(email: str, user: dict = Depends(require_admin), limit: int = 10):
    """Surface why a given user is getting their current recommendations.

    Returns the top-N candidates with score breakdown so we can debug
    user reports of "bad feed".
    """
    from core import get_catalog, movie_matches, movie_score, movie_reason
    email_n = (email or "").lower().strip()
    target = await db.users.find_one({"email": email_n}, {"_id": 0, "password_hash": 0})
    if not target:
        raise HTTPException(404, "User not found")

    catalog = get_catalog()
    seen = set(
        (target.get("saved") or []) + (target.get("watched") or []) +
        (target.get("skipped") or []) + (target.get("onboarding_rated") or [])
    )
    candidates = [m for m in catalog if m["id"] not in seen and movie_matches(m, target)]
    scored = sorted(
        ((m, movie_score(m, target)) for m in candidates),
        key=lambda kv: kv[1],
        reverse=True,
    )[:limit]
    return {
        "user_id": target["user_id"],
        "email": target["email"],
        "pool_size": len(candidates),
        "subscriptions": target.get("subscriptions") or [],
        "top_genres": sorted(
            (target.get("genre_weights") or {}).items(),
            key=lambda kv: kv[1], reverse=True
        )[:8],
        "candidates": [
            {
                "id": m["id"],
                "title": m.get("title"),
                "year": m.get("year"),
                "score": round(float(s), 3),
                "genres": m.get("genres"),
                "available_on": m.get("available_on"),
                "reason": movie_reason(m, target),
            }
            for m, s in scored
        ],
    }


@router.get("/catalogue-health")
async def admin_catalogue_health(user: dict = Depends(require_admin)):
    """Comprehensive catalogue health & metadata coverage report.

    Surfaces:
      - total titles, counts per genre, counts per provider per region
      - coverage % for: cast, director, keywords, poster, trailer, runtime,
        overview, status, providers
      - stale provider records (enriched > 30 days ago)
      - low-quality-but-Discover-eligible titles (passes quality gate but
        missing cast/keywords/runtime — flagged for re-enrichment)
    """
    total = await db.movies_cache.count_documents({})
    if total == 0:
        return {"total": 0, "note": "Catalogue empty — run /admin/bulk-import"}

    # ── Coverage counts (in parallel) ─────────────────────────────────────
    (
        with_poster, with_overview, with_trailer, with_cast, with_director,
        with_writer, with_studio, with_keywords, with_runtime, with_status,
        with_any_provider, with_collection, with_themes, with_franchises,
        movies, tv_shows, high_rated,
    ) = await asyncio.gather(
        db.movies_cache.count_documents({"poster_url":     {"$nin": [None, ""]}}),
        db.movies_cache.count_documents({"overview":       {"$nin": [None, ""]}}),
        db.movies_cache.count_documents({"trailer_youtube_id": {"$nin": [None, ""]}}),
        db.movies_cache.count_documents({"cast_names.0":   {"$exists": True}}),
        db.movies_cache.count_documents({"director_names.0": {"$exists": True}}),
        db.movies_cache.count_documents({"writer_names.0": {"$exists": True}}),
        db.movies_cache.count_documents({"studio_names.0": {"$exists": True}}),
        db.movies_cache.count_documents({"keywords.0":     {"$exists": True}}),
        db.movies_cache.count_documents({"runtime":        {"$gt": 0}}),
        db.movies_cache.count_documents({"status":         {"$nin": [None, ""]}}),
        db.movies_cache.count_documents({"$or": [
            {"available_on.0": {"$exists": True}},
            {"rent_on.0":      {"$exists": True}},
            {"buy_on.0":       {"$exists": True}},
        ]}),
        db.movies_cache.count_documents({"collection_name": {"$nin": [None, ""]}}),
        db.movies_cache.count_documents({"themes.0":     {"$exists": True}}),
        db.movies_cache.count_documents({"franchises.0": {"$exists": True}}),
        db.movies_cache.count_documents({"type": "movie"}),
        db.movies_cache.count_documents({"type": "tv"}),
        db.movies_cache.count_documents({"rating": {"$gte": 7.5}}),
    )

    def pct(n: int) -> float:
        return round((n / total) * 100, 1) if total else 0.0

    coverage = {
        "poster":    {"count": with_poster,       "pct": pct(with_poster)},
        "overview":  {"count": with_overview,     "pct": pct(with_overview)},
        "trailer":   {"count": with_trailer,      "pct": pct(with_trailer)},
        "cast":      {"count": with_cast,         "pct": pct(with_cast)},
        "director":  {"count": with_director,     "pct": pct(with_director)},
        "writer":    {"count": with_writer,       "pct": pct(with_writer)},
        "studio":    {"count": with_studio,       "pct": pct(with_studio)},
        "keywords":  {"count": with_keywords,     "pct": pct(with_keywords)},
        "runtime":   {"count": with_runtime,      "pct": pct(with_runtime)},
        "status":    {"count": with_status,       "pct": pct(with_status)},
        "providers": {"count": with_any_provider, "pct": pct(with_any_provider)},
        "collection":{"count": with_collection,   "pct": pct(with_collection)},
        "themes":    {"count": with_themes,       "pct": pct(with_themes)},
        "franchises":{"count": with_franchises,   "pct": pct(with_franchises)},
    }

    # ── Per-genre counts (one aggregation pass) ───────────────────────────
    genre_counts: dict[str, int] = {}
    async for row in db.movies_cache.aggregate([
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort":  {"count": -1}},
    ]):
        genre_counts[row["_id"]] = row["count"]

    # ── Provider × region matrix ──────────────────────────────────────────
    # Counts are region-scoped via `providers_region` (written by
    # enrich_providers_top).  Titles enriched before that field existed
    # contribute to a synthetic "unknown" region bucket so the totals stay
    # consistent with `coverage.providers`.
    from catalog_import import _PROVIDER_IDS_BY_REGION
    region_names = list(_PROVIDER_IDS_BY_REGION.keys()) + ["unknown"]
    all_providers = sorted({n for plist in _PROVIDER_IDS_BY_REGION.values() for _, n in plist})

    by_provider_region: dict[str, dict[str, int]] = {r: {} for r in region_names}
    flat_keys: list[tuple[str, str]] = []
    region_tasks = []
    for region in region_names:
        for name in all_providers:
            if region in _PROVIDER_IDS_BY_REGION and name not in {n for _, n in _PROVIDER_IDS_BY_REGION[region]}:
                continue  # provider not offered in this region
            flat_keys.append((region, name))
            if region == "unknown":
                region_tasks.append(db.movies_cache.count_documents({
                    "available_on": name,
                    "providers_region": {"$exists": False},
                }))
            else:
                region_tasks.append(db.movies_cache.count_documents({
                    "available_on": name,
                    "providers_region": region,
                }))
    counts = await asyncio.gather(*region_tasks)
    for (region, name), c in zip(flat_keys, counts):
        by_provider_region[region][name] = c

    # ── Stale provider records (enriched > 30 days ago) ───────────────────
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    stale_providers = await db.movies_cache.count_documents({
        "providers_fetched": True,
        "providers_fetched_at": {"$lt": stale_cutoff},
    })

    # ── Low-quality-but-eligible: passes catalog_quality_gate but is still
    # missing rich metadata (cast / keywords / runtime). Computed in-process
    # against the in-memory catalogue so the count matches what Discover
    # actually sees — DB filters cannot replicate the gate's logic exactly.
    from core import catalog_quality_gate as _gate
    low_quality_eligible = 0
    for m in get_catalog():
        if not _gate(m):
            continue
        if (
            not (m.get("cast_names") or [])
            or not (m.get("keywords") or [])
            or (m.get("type") == "movie" and not (m.get("runtime") or 0))
        ):
            low_quality_eligible += 1

    return {
        "total":           total,
        "movies":          movies,
        "tv_shows":        tv_shows,
        "high_rated_gte_7_5": high_rated,
        "in_memory":       len(get_catalog()),
        "coverage":        coverage,
        "genre_counts":    genre_counts,
        "by_provider_region": by_provider_region,
        "stale_providers": stale_providers,
        "low_quality_eligible": low_quality_eligible,
    }


@router.get("/diagnostics/recommendations")
async def admin_diagnostics_recommendations(user: dict = Depends(require_admin)):
    """Recommendation & catalogue health diagnostics (Part 8 — observability).

    Read-only: this endpoint never touches recommendation behaviour, scoring or
    feed building. It aggregates metrics with simple queries plus in-Python
    aggregation (no database aggregation pipelines — the managed DB rejects
    them). Every metric returns ``null`` when it cannot be computed rather than
    raising, and each section is independently guarded so a single failure can
    never crash the whole dashboard.

    Sections:
      - catalogue: total, eligible, Tier A/B/C/D counts
      - freshness: fresh-eligible count + repeat-recommendation rate (impressions)
      - users: heavy-user count (engine definition)
      - recommendation_health: directional diversity score (0-100)
    """
    import os as _os
    from core import get_catalog, catalog_quality_gate
    from content_cards import compute_quality_score
    from engine import HEAVY_USER_SWIPES, HEAVY_FRESH_FLOOR

    default_region = (_os.environ.get("TMDB_REGION") or "GB").upper()
    catalog = get_catalog()
    total_catalogue = len(catalog)

    # ── Catalogue metrics: eligibility + quality tiers ────────────────────
    eligible = None
    eligible_ids: set = set()
    tier_counts = None
    if total_catalogue:
        tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        eligible = 0
        for m in catalog:
            try:
                if catalog_quality_gate(m, user_region=default_region):
                    eligible += 1
                    eligible_ids.add(m["id"])
            except Exception:
                pass
            try:
                _, tier = compute_quality_score(m)
                if tier in tier_counts:
                    tier_counts[tier] += 1
            except Exception:
                pass

    catalogue = {
        "total":    total_catalogue or None,
        "eligible": eligible,
        "tier_a":   tier_counts["A"] if tier_counts else None,
        "tier_b":   tier_counts["B"] if tier_counts else None,
        "tier_c":   tier_counts["C"] if tier_counts else None,
        "tier_d":   tier_counts["D"] if tier_counts else None,
    }

    # ── Freshness: recently-recommended set + repeat rate (impressions) ───
    # Prefer the last 7 days; if that window is too thin, fall back to the most
    # recent ~500 recommendation events, whichever fits the data.
    MIN_EVENTS = 30
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    all_rows: list = []  # (movie_id, at) most-recent first
    try:
        cursor = db.impressions.find(
            {}, {"_id": 0, "items.id": 1, "at": 1}
        ).sort("at", -1).limit(600)
        async for doc in cursor:
            at = doc.get("at") or ""
            for it in (doc.get("items") or []):
                mid = it.get("id")
                if mid is not None:
                    all_rows.append((mid, at))
    except Exception:
        all_rows = []

    rows_7d = [r for r in all_rows if r[1] >= cutoff_iso]
    if len(rows_7d) >= MIN_EVENTS:
        window, window_label = rows_7d, "last_7_days"
    else:
        window, window_label = all_rows[:500], "last_500_events"

    window_ids = [mid for mid, _ in window]
    total_events = len(window_ids)
    distinct_events = len(set(window_ids))
    recommended_recent = set(window_ids)

    repeat_rate = (
        round((1 - distinct_events / total_events) * 100, 1)
        if total_events >= MIN_EVENTS else None
    )

    fresh_eligible = len(eligible_ids - recommended_recent) if eligible is not None else None

    freshness = {
        "fresh_eligible":  fresh_eligible,
        "repeat_rate_pct": repeat_rate,
        "events_analysed": total_events or None,
        "window":          window_label if total_events else None,
    }

    # ── Heavy-user count (engine definition, directionally approximated) ──
    # A user is "heavy" when interactions >= HEAVY_USER_SWIPES, OR fewer than
    # HEAVY_FRESH_FLOOR fresh-eligible titles remain. Per-user fresh-eligible is
    # approximated as (eligible catalogue − titles already seen) to avoid
    # rebuilding each user's filtered pool.
    heavy_users = None
    total_users = None
    try:
        heavy = 0
        counted = 0
        cursor = db.users.find(
            {}, {"_id": 0, "saved": 1, "watched": 1,
                 "skipped": 1, "onboarding_rated": 1}
        )
        async for u in cursor:
            counted += 1
            interactions = (
                len(u.get("saved") or []) + len(u.get("watched") or [])
                + len(u.get("skipped") or []) + len(u.get("onboarding_rated") or [])
            )
            if eligible_ids:
                seen = set(
                    (u.get("saved") or []) + (u.get("watched") or [])
                    + (u.get("skipped") or []) + (u.get("onboarding_rated") or [])
                )
                user_fresh = len(eligible_ids - seen)
            else:
                user_fresh = None
            is_heavy = interactions >= HEAVY_USER_SWIPES or (
                user_fresh is not None and user_fresh < HEAVY_FRESH_FLOOR
            )
            if is_heavy:
                heavy += 1
        if counted:
            heavy_users = heavy
            total_users = counted
    except Exception:
        heavy_users = None

    users = {"heavy_users": heavy_users, "total_users": total_users}

    # ── Recommendation health: directional diversity score (0-100) ───────
    # Sampled from the most recent served feeds. Blends genre spread, anti-streak
    # (repeated adjacent genre), franchise repetition and overall title variety.
    # Not mathematically exact — a useful directional signal only.
    diversity = None
    feeds_analysed = 0
    try:
        catalog_by_id = {m["id"]: m for m in catalog}
        feeds: list = []
        cursor = db.impressions.find(
            {}, {"_id": 0, "items.id": 1}
        ).sort("at", -1).limit(50)
        async for doc in cursor:
            ids = [it.get("id") for it in (doc.get("items") or []) if it.get("id") is not None]
            if ids:
                feeds.append(ids)
        feeds_analysed = len(feeds)
        if feeds:
            all_genres: set = set()
            total_pairs = same_genre_pairs = 0
            total_items = 0
            distinct_items: set = set()
            franchise_repeat = 0
            for ids in feeds:
                prev_genres = None
                seen_coll: set = set()
                for mid in ids:
                    total_items += 1
                    distinct_items.add(mid)
                    m = catalog_by_id.get(mid)
                    if not m:
                        prev_genres = None
                        continue
                    g = set(m.get("genres") or [])
                    all_genres |= g
                    if prev_genres is not None:
                        total_pairs += 1
                        if g & prev_genres:
                            same_genre_pairs += 1
                    prev_genres = g
                    coll = (m.get("collection_name") or "").strip()
                    if coll:
                        if coll in seen_coll:
                            franchise_repeat += 1
                        else:
                            seen_coll.add(coll)
            genre_spread   = min(1.0, len(all_genres) / 12.0)
            variety        = (len(distinct_items) / total_items) if total_items else 0.0
            run_score      = (1.0 - same_genre_pairs / total_pairs) if total_pairs else 1.0
            franchise_score = (1.0 - franchise_repeat / total_items) if total_items else 1.0
            diversity = int(round(100 * (
                0.30 * genre_spread + 0.30 * variety
                + 0.25 * run_score + 0.15 * franchise_score
            )))
    except Exception:
        diversity = None

    recommendation_health = {
        "diversity_score": diversity,
        "feeds_analysed":  feeds_analysed or None,
    }

    return {
        "catalogue":             catalogue,
        "freshness":             freshness,
        "users":                 users,
        "recommendation_health": recommendation_health,
        "generated_at":          datetime.now(timezone.utc).isoformat(),
    }


@router.get("/diagnostics/impression-conversions")
async def admin_impression_conversions(user: dict = Depends(require_admin)):
    """Read-only conversion report for recent recommendation impressions."""
    from content_cards import compute_quality_score

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    report = {
        "summary": {"impressions": None, "responded": None, "response_rate_pct": None},
        "by_reason_code": [],
        "by_slot": [],
        "by_quality_tier": [],
        "window": "last_90_days",
        "feeds_analysed": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        cursor = db.impressions.find(
            {"at": {"$gte": cutoff}},
            {"_id": 0, "user_id": 1, "impression_id": 1, "at": 1, "items": 1},
        ).sort("at", -1).limit(500)
        impressions = [doc async for doc in cursor]
        impression_ids = [
            doc.get("impression_id") for doc in impressions if doc.get("impression_id")
        ]
        actions = []
        if impression_ids:
            action_cursor = db.user_actions.find(
                {"impression_id": {"$in": impression_ids}},
                {"_id": 0, "user_id": 1, "impression_id": 1, "movie_id": 1,
                 "action": 1, "created_at": 1},
            ).sort("created_at", 1)
            actions = [doc async for doc in action_cursor]

        quality_tiers = {}
        for movie in get_catalog():
            try:
                quality_tiers[movie["id"]] = compute_quality_score(movie)[1]
            except Exception:
                continue
        report.update(_build_impression_conversion_report(
            impressions, actions, quality_tiers
        ))
        report["feeds_analysed"] = len(impressions)
    except Exception:
        logger.exception("Could not build impression conversion diagnostics")
    return report


@router.get("/provider-health")
async def admin_provider_health(user: dict = Depends(require_admin)):
    """Provider data coverage + trust — how complete and fresh is our
    'where to watch' info, broken down by region, content type, and confidence."""
    from core import get_catalog
    from providers_util import (
        compute_confidence, resolve_region_providers,
        SUPPORTED_REGIONS, DEFAULT_REGION, _is_stale,
    )
    catalog = get_catalog()
    total = len(catalog)
    with_any = sum(1 for m in catalog if m.get("available_on") or m.get("rent_on") or m.get("buy_on"))
    enriched = sum(1 for m in catalog if m.get("providers_fetched") is True)
    pending = sum(1 for m in catalog if m.get("providers_fetched") is not True)
    by_service: dict[str, int] = {}
    for m in catalog:
        for s in (m.get("available_on") or []):
            by_service[s] = by_service.get(s, 0) + 1

    # ── Confidence distribution + content-type breakdown (default region) ──────
    confidence_dist = {"high": 0, "medium": 0, "low": 0, "none": 0}
    by_content_type = {
        "movie": {"total": 0, "with_any": 0, "enriched": 0},
        "tv":    {"total": 0, "with_any": 0, "enriched": 0},
    }
    stale = 0
    for m in catalog:
        conf = compute_confidence(
            m.get("available_on") or [], m.get("rent_on") or [], m.get("buy_on") or [],
            m.get("providers_fetched_at"), bool(m.get("providers_empty_confirmed")),
        )
        confidence_dist[conf] = confidence_dist.get(conf, 0) + 1
        if m.get("providers_fetched") is True and _is_stale(m.get("providers_fetched_at")):
            stale += 1
        ct = "tv" if m.get("type") == "tv" else "movie"
        bucket = by_content_type[ct]
        bucket["total"] += 1
        if m.get("available_on") or m.get("rent_on") or m.get("buy_on"):
            bucket["with_any"] += 1
        if m.get("providers_fetched") is True:
            bucket["enriched"] += 1

    # ── Per-region coverage from the DB (canonical region-keyed store) ─────────
    by_region: dict[str, dict] = {}
    for region in SUPPORTED_REGIONS:
        present = await db.movies_cache.count_documents(
            {f"providers_by_region.{region}": {"$exists": True}}
        )
        by_region[region] = {"stored": present}
    # Default region also covered by legacy flat fields.
    by_region.setdefault(DEFAULT_REGION, {})["legacy_flat_enriched"] = enriched

    # ── Region × content-type matrix ──────────────────────────────────────────
    # For every supported region, resolve each in-memory title against that
    # region and break results down by content type: how many titles we hold
    # trustworthy data for, how many are missing/stale, and the confidence mix.
    def _empty_slice() -> dict:
        return {
            "total": 0, "matched": 0, "with_any": 0, "missing": 0, "stale": 0,
            "confidence": {"high": 0, "medium": 0, "low": 0, "none": 0},
        }

    region_matrix: dict[str, dict] = {}
    for region in SUPPORTED_REGIONS:
        slices = {"movie": _empty_slice(), "tv": _empty_slice()}
        for m in catalog:
            ct = "tv" if m.get("type") == "tv" else "movie"
            s = slices[ct]
            s["total"] += 1
            res = resolve_region_providers(m, region)
            has_any = bool(res["available_on"] or res["rent_on"] or res["buy_on"])
            if res["region_matched"]:
                s["matched"] += 1
                if has_any:
                    s["with_any"] += 1
                else:
                    s["missing"] += 1
                if res["stale"]:
                    s["stale"] += 1
            else:
                # No trustworthy data for this region at all.
                s["missing"] += 1
                s["stale"] += 1
            s["confidence"][res["confidence"]] = s["confidence"].get(res["confidence"], 0) + 1
        region_matrix[region] = slices

    return {
        "in_memory_total": total,
        "with_any_provider": with_any,
        "providers_enriched": enriched,
        "providers_pending": pending,
        "providers_missing": total - with_any,
        "providers_stale": stale,
        "coverage_pct": round((with_any / total * 100) if total else 0, 1),
        "confidence_distribution": confidence_dist,
        "by_content_type": by_content_type,
        "by_region": by_region,
        "region_matrix": region_matrix,
        "default_region": DEFAULT_REGION,
        "by_subscription_service": dict(sorted(by_service.items(), key=lambda kv: kv[1], reverse=True)),
    }


@router.get("/issue-reports")
async def admin_issue_reports(
    user: dict = Depends(require_admin),
    status: str | None = None,
    limit: int = 200,
):
    """List user-submitted issue reports (newest first), optionally by status."""
    query: dict = {}
    if status:
        query["status"] = status
    rows = []
    async for doc in db.issue_reports.find(query).sort("created_at", -1).limit(limit):
        doc["report_id"] = str(doc.pop("_id"))
        rows.append(doc)
    # Summary counts by status + reason for a quick triage view.
    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    async for doc in db.issue_reports.find({}, {"status": 1, "reason": 1}):
        by_status[doc.get("status", "open")] = by_status.get(doc.get("status", "open"), 0) + 1
        by_reason[doc.get("reason", "other")] = by_reason.get(doc.get("reason", "other"), 0) + 1
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_reason": by_reason,
        "reports": rows,
    }


@router.post("/issue-reports/{report_id}/resolve")
async def admin_resolve_issue_report(
    report_id: str,
    user: dict = Depends(require_admin),
    status: str = "resolved",
):
    """Mark an issue report resolved/dismissed."""
    from bson import ObjectId
    try:
        oid = ObjectId(report_id)
    except Exception:
        raise HTTPException(400, "Invalid report id")
    if status not in ("open", "resolved", "dismissed"):
        raise HTTPException(400, "Invalid status")
    res = await db.issue_reports.update_one(
        {"_id": oid},
        {"$set": {"status": status, "resolved_at": datetime.now(timezone.utc).isoformat(),
                  "resolved_by": user["user_id"]}},
    )
    if not res.matched_count:
        raise HTTPException(404, "Report not found")
    return {"ok": True, "report_id": report_id, "status": status}


@router.get("/users")
async def admin_users(user: dict = Depends(require_admin), limit: int = 200):
    """Return a list of all users with summary debug data (no passwords, no large arrays)."""
    rows = []
    async for doc in db.users.find({}, {"_id": 0, "password_hash": 0, "recently_shown": 0, "onboarding_rated": 0}).sort("created_at", -1).limit(limit):
        rows.append({
            "user_id":              doc.get("user_id"),
            "email":                doc.get("email"),
            "name":                 doc.get("name"),
            "role":                 doc.get("role", "user"),
            "auth_provider":        doc.get("auth_provider", "password"),
            "created_at":           doc.get("created_at"),
            "last_action_at":       doc.get("last_action_at"),
            "onboarding_completed": doc.get("onboarding_completed", False),
            "subscriptions":        doc.get("subscriptions") or [],
            "genres":               doc.get("genres") or [],
            "excluded_categories":  doc.get("excluded_categories") or [],
            "content_type":         doc.get("content_type", "both"),
            "saved_count":          len(doc.get("saved") or []),
            "watched_count":        len(doc.get("watched") or []),
            "skipped_count":        len(doc.get("skipped") or []),
            "exploration_weight":   round(float(doc.get("exploration_weight") or 0.5), 3),
            "top_genres":           sorted(
                (doc.get("genre_weights") or {}).items(),
                key=lambda kv: kv[1], reverse=True
            )[:5],
        })
    return rows


@router.get("/dashboard")
async def admin_dashboard(user: dict = Depends(require_admin)):
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
    recent = []
    async for r in db.affiliate_clicks.find({}, {"_id": 0}).sort("created_at", -1).limit(20):
        recent.append({
            "created_at": r.get("created_at"),
            "user_id": r.get("user_id"),
            "service_name": r.get("service_name"),
            "movie_title": r.get("movie_title"),
        })
    return {
        "catalog_size": len(get_catalog()),
        "total_users": total_users,
        "total_clicks": total_clicks,
        "unique_click_users": unique_click_users,
        "by_service": by_service,
        "recent": recent,
    }


@router.get("/analytics")
async def admin_analytics(user: dict = Depends(require_admin)):
    """Internal analytics: DAU, retention, swipe behaviour."""
    now = datetime.now(timezone.utc)
    today_iso = (now - timedelta(days=1)).isoformat()
    week_iso = (now - timedelta(days=7)).isoformat()
    month_iso = (now - timedelta(days=30)).isoformat()

    dau = len(await db.user_actions.distinct("user_id", {"created_at": {"$gte": today_iso}}))
    wau = len(await db.user_actions.distinct("user_id", {"created_at": {"$gte": week_iso}}))
    mau = len(await db.user_actions.distinct("user_id", {"created_at": {"$gte": month_iso}}))

    swipe_pipeline = [
        {"$match": {"created_at": {"$gte": week_iso}}},
        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
    ]
    swipes = {}
    async for row in db.user_actions.aggregate(swipe_pipeline):
        swipes[row["_id"]] = row["count"]
    total_swipes = sum(swipes.values()) or 1
    save_rate = round(swipes.get("save", 0) / total_swipes * 100, 1)

    return {
        "dau": dau, "wau": wau, "mau": mau,
        "swipes_7d": swipes,
        "save_rate_pct": save_rate,
        "total_users": await db.users.count_documents({}),
    }


@router.get("/diagnostics/community")
async def admin_diagnostics_community(user: dict = Depends(require_admin)):
    """Community learning diagnostics: aggregate title metrics, top/bottom
    performers, self-cleaning candidates, and cluster distribution.

    Read-only; every metric guarded so one failure never kills the response.
    """
    from global_learning import community_health_snapshot
    return await community_health_snapshot()


@router.post("/recompute-metrics")
async def admin_recompute_metrics(user: dict = Depends(require_admin)):
    """Trigger a full recompute of title-level metrics AND taste clusters.

    This is the operational pipeline that ensures community data actually exists.
    Call after significant catalog changes or periodically (e.g. daily cron).
    """
    from global_learning import compute_title_metrics, build_taste_clusters
    metrics_result = await compute_title_metrics()
    cluster_result = await build_taste_clusters()
    return {
        "metrics": metrics_result,
        "clusters": cluster_result,
    }


@router.get("/catalog-age-audit")
async def admin_catalog_age_audit(
    user: dict = Depends(require_admin),
    region: str = "GB",
):
    """Diagnostic of release-year eligibility across the catalog.

    Reports how many titles survive the new age gate, counts per decade,
    oldest survivors, and per-provider breakdowns. Used to validate thresholds
    before deploying to production and to spot provider-specific leaks.
    """
    catalog = get_catalog()
    if not catalog:
        return {"error": "catalog_empty"}

    # Buckets are for ELIGIBLE titles only (gate effectiveness measure)
    eligible_buckets = {"pre_1950": 0, "1950_1979": 0, "1980_1994": 0, "1995_1999": 0,
                        "2000_2004": 0, "2005_2009": 0, "2010_plus": 0, "unknown": 0}
    # Raw buckets for comparison
    raw_buckets = {"pre_1950": 0, "1950_1979": 0, "1980_1994": 0, "1995_1999": 0,
                   "2000_2004": 0, "2005_2009": 0, "2010_plus": 0, "unknown": 0}
    # Per-provider breakdowns (eligible-only)
    provider_stats: dict[str, dict] = {}
    oldest_survivors: list[dict] = []
    total = len(catalog)
    eligible_count = 0

    def _bucket(year, _dict):
        if not year:
            _dict["unknown"] += 1
        elif year < 1950:
            _dict["pre_1950"] += 1
        elif year < 1980:
            _dict["1950_1979"] += 1
        elif year < 1995:
            _dict["1980_1994"] += 1
        elif year < 2000:
            _dict["1995_1999"] += 1
        elif year < 2005:
            _dict["2000_2004"] += 1
        elif year < 2010:
            _dict["2005_2009"] += 1
        else:
            _dict["2010_plus"] += 1

    for m in catalog:
        year = int(m.get("year") or 0)
        _bucket(year, raw_buckets)
        is_eligible = catalog_quality_gate(m, user_region=region)
        if is_eligible:
            eligible_count += 1
            _bucket(year, eligible_buckets)
            # Eligible provider breakdown (region-resolved, same semantics as eligibility)
            _resolved = resolve_region_providers(m, region)
            _region_providers = (
                (_resolved.get("available_on") or []) +
                (_resolved.get("rent_on") or []) +
                (_resolved.get("buy_on") or [])
            )
            for svc in set(_region_providers):
                if svc not in provider_stats:
                    provider_stats[svc] = {
                        "eligible_count": 0, "oldest_year": 9999, "youngest_year": 0,
                        "year_sum": 0, "pre_2005": 0, "pre_2000": 0, "pre_1980": 0,
                        "years": [],
                    }
                s = provider_stats[svc]
                s["eligible_count"] += 1
                if year:
                    s["oldest_year"] = min(s["oldest_year"], year)
                    s["youngest_year"] = max(s["youngest_year"], year)
                    s["year_sum"] += year
                    s["years"].append(year)
                    if year < 2005:
                        s["pre_2005"] += 1
                    if year < 2000:
                        s["pre_2000"] += 1
                    if year < 1980:
                        s["pre_1980"] += 1

            # Oldest eligible survivors (with gate reason)
            if year and year < 2000:
                _reason = (
                    "classic_exception" if _classic_exception_ok(m)
                    else "tv_floor_1995" if m.get("type") != "movie" and year >= 1995
                    else "unknown"
                )
                oldest_survivors.append({
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "year": year,
                    "type": m.get("type"),
                    "rating": m.get("rating"),
                    "vote_count": m.get("vote_count"),
                    "popularity": m.get("popularity"),
                    "language": m.get("original_language"),
                    "providers": m.get("available_on"),
                    "classic_exception": _classic_exception_ok(m),
                    "age_tier": _age_tier(m),
                    "reason": _reason,
                })

    oldest_survivors.sort(key=lambda x: x["year"])
    oldest_survivors = oldest_survivors[:100]

    # Compute provider avg/median year and drop internal year lists
    for s in provider_stats.values():
        years = s.pop("years", [])
        n = s["eligible_count"]
        s["avg_year"] = round(s.pop("year_sum", 0) / n, 1) if n else None
        s["median_year"] = round(sorted(years)[len(years) // 2], 1) if years else None

    # Admission-path breakdown (eligible titles only, by where they entered the system)
    path_counts = {"normal": 0, "discovery": 0, "fallback": 0, "reintro": 0, "sync": 0}
    for m in catalog:
        if not catalog_quality_gate(m, user_region=region):
            continue
        src = (m.get("source") or "").lower()
        if "discover" in src or m.get("discover_section"):
            path_counts["discovery"] += 1
        elif "fallback" in src:
            path_counts["fallback"] += 1
        elif "reintro" in src or m.get("reintroduced"):
            path_counts["reintro"] += 1
        elif "sync" in src:
            path_counts["sync"] += 1
        else:
            path_counts["normal"] += 1

    # Pool-shortage safety check: per major provider + overall movie/tv
    # Uses region-resolved providers (same semantics as eligibility gate).
    MAJOR_PROVIDERS = {"netflix", "prime_video", "disney_plus", "hbo_max",
                       "hulu", "apple_tv", "paramount_plus", "peacock"}
    _provider_counts: dict[str, int] = {}
    _type_counts = {"movie": 0, "tv": 0}
    for m in catalog:
        if catalog_quality_gate(m, user_region=region):
            t = m.get("type")
            if t in _type_counts:
                _type_counts[t] += 1
            _r2 = resolve_region_providers(m, region)
            _region_providers2 = (
                (_r2.get("available_on") or []) +
                (_r2.get("rent_on") or []) +
                (_r2.get("buy_on") or [])
            )
            for svc in set(_region_providers2):
                _provider_counts[svc] = _provider_counts.get(svc, 0) + 1
    shortages = {}
    for t, cnt in _type_counts.items():
        if cnt < 50:
            shortages[t] = cnt
    for svc, cnt in _provider_counts.items():
        if svc in MAJOR_PROVIDERS and cnt < 20:
            shortages[f"provider:{svc}"] = cnt

    return {
        "catalog_total": total,
        "eligible_count": eligible_count,
        "raw_buckets": raw_buckets,
        "eligible_buckets": eligible_buckets,
        "provider_breakdown": provider_stats,
        "path_breakdown": path_counts,
        "oldest_survivors": oldest_survivors,
        "shortages": shortages,
    }


@router.get("/people-affinity/{user_id}")
async def admin_people_affinity(
    user_id: str,
    user: dict = Depends(require_admin),
):
    """Diagnostics-only: show per-user actor/director/writer affinity weights.

    Read-only — never changes recommendation ranking.  Reports top people by
    weight, interaction counts, and rough correlation hints so the correlation
    measurement step (Task #37 Phase 4) has data to analyse.
    """
    from taste import build_taste_profile

    doc = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "saved": 1, "watched": 1, "skipped": 1,
         "genre_weights": 1, "cast_weights": 1, "director_weights": 1,
         "writer_weights": 1, "exploration_weight": 1, "taste_profile": 1},
    )
    if not doc:
        raise HTTPException(404, "user not found")

    def _top(weights: dict | None, n: int = 10, *, positive: bool = True) -> list[dict]:
        if not weights:
            return []
        items = [(k, v) for k, v in weights.items()
                 if (v > 0 if positive else True)]
        items.sort(key=lambda kv: kv[1], reverse=True)
        out = []
        for name, w in items[:n]:
            entry = {"name": name, "weight": round(w, 3)}
            if positive:
                entry["strength"] = (
                    "strong" if w >= 3 else "moderate" if w >= 1 else "weak"
                )
            out.append(entry)
        return out

    # Count how many of the user's saved/watched/skipped titles actually carry
    # people metadata so we know whether affinity is tracking against data or
    # against empty fields.
    saved = doc.get("saved") or []
    watched = doc.get("watched") or []
    skipped = doc.get("skipped") or []
    all_ids = list(set(saved + watched + skipped))
    catalog = get_catalog()
    catalog_by_id = {m["id"]: m for m in catalog}

    people_counts: dict[str, dict] = {}
    total_with_people = 0
    for mid in all_ids:
        m = catalog_by_id.get(mid)
        if not m:
            continue
        has_any = False
        for field in ("cast_names", "director_names", "writer_names"):
            for p in (m.get(field) or []):
                has_any = True
                key = f"{field}:{p.lower()}"
                people_counts.setdefault(key, {"name": p, "role": field.replace("_names", ""),
                                               "positive": 0, "negative": 0})
                if mid in saved or mid in watched:
                    people_counts[key]["positive"] += 1
                elif mid in skipped:
                    people_counts[key]["negative"] += 1
        if has_any:
            total_with_people += 1

    # Correlation hint: ratio of positive interactions to total for each person
    top_people = sorted(
        people_counts.values(),
        key=lambda d: d["positive"] - d["negative"],
        reverse=True,
    )[:20]

    # Compute how many of the user's top-weighted people actually appear in
    # their positive (saved/watched) titles vs their skipped titles — a crude
    # directional correlation check.
    cast_w = doc.get("cast_weights") or {}
    director_w = doc.get("director_weights") or {}
    writer_w = doc.get("writer_weights") or {}
    total_people = len(cast_w) + len(director_w) + len(writer_w)

    def _correlation_hint(weights: dict, field: str) -> dict:
        """Count per-person positive/negative interactions using the already-
        computed people_counts (deterministic, field-accurate, no early break)."""
        if not weights:
            return {"tracked": 0, "in_positive": 0, "in_negative": 0, "only_skipped": 0}
        tracked = 0
        in_pos = 0
        in_neg = 0
        only_skipped = 0
        for name in weights:
            key = f"{field}:{name.lower()}"
            pc = people_counts.get(key)
            if not pc:
                continue
            tracked += 1
            pos = pc["positive"]
            neg = pc["negative"]
            in_pos += pos
            in_neg += neg
            if neg > 0 and pos == 0:
                only_skipped += 1
        return {
            "tracked": tracked,
            "in_positive": in_pos,
            "in_negative": in_neg,
            "only_skipped": only_skipped,
        }

    taste = build_taste_profile(doc)

    return {
        "user_id": user_id,
        "interactions": {
            "saved": len(saved),
            "watched": len(watched),
            "skipped": len(skipped),
            "titles_with_people_metadata": total_with_people,
            "titles_without_people_metadata": len(all_ids) - total_with_people,
        },
        "top_cast": _top(cast_w, 10),
        "top_directors": _top(director_w, 10),
        "top_writers": _top(writer_w, 10),
        "people_interaction_breakdown": top_people,
        "correlation_hints": {
            "cast": _correlation_hint(cast_w, "cast_names"),
            "director": _correlation_hint(director_w, "director_names"),
            "writer": _correlation_hint(writer_w, "writer_names"),
        },
        "taste_profile_people": {
            "cast_affinity": taste.get("cast_affinity"),
            "director_affinity": taste.get("director_affinity"),
            "writer_affinity": taste.get("writer_affinity"),
        },
        "total_tracked_people": total_people,
    }


@router.get("/people-correlation/{user_id}")
async def admin_people_correlation(
    user_id: str,
    user: dict = Depends(require_admin),
):
    """Concrete correlation measurement for people affinity (Task #37 Phase 3).

    Computes a clean baseline-vs-high-affinity conversion comparison:
      - "exposed" titles: those featuring any of the user's top-weighted people
      - "control" titles: all other interacted titles without those people
      - conversion rate on exposed vs control, plus effect size (lift)

    This gives Phase 4 gating a measured yes/no effect size instead of hints.
    """
    from taste import build_taste_profile

    doc = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "saved": 1, "watched": 1, "skipped": 1,
         "cast_weights": 1, "director_weights": 1, "writer_weights": 1},
    )
    if not doc:
        raise HTTPException(404, "user not found")

    saved = doc.get("saved") or []
    watched = doc.get("watched") or []
    skipped = doc.get("skipped") or []
    all_ids = list(set(saved + watched + skipped))
    if not all_ids:
        return {"user_id": user_id, "note": "no interactions yet", "lift": None}

    catalog = get_catalog()
    catalog_by_id = {m["id"]: m for m in catalog}

    # Top-weighted people (anyone with positive weight)
    top_people: set[str] = set()
    for field in ("cast_weights", "director_weights", "writer_weights"):
        weights = doc.get(field) or {}
        for name, w in weights.items():
            if w > 0:
                top_people.add(name.lower())

    if not top_people:
        return {"user_id": user_id, "note": "no positive affinity yet", "lift": None}

    exposed_pos = 0
    exposed_neg = 0
    control_pos = 0
    control_neg = 0

    for mid in all_ids:
        m = catalog_by_id.get(mid)
        if not m:
            continue
        people_here = set()
        for field in ("cast_names", "director_names", "writer_names"):
            for p in (m.get(field) or []):
                people_here.add(str(p).lower())
        is_exposed = bool(people_here & top_people)
        is_pos = mid in saved or mid in watched
        if is_exposed:
            if is_pos:
                exposed_pos += 1
            else:
                exposed_neg += 1
        else:
            if is_pos:
                control_pos += 1
            else:
                control_neg += 1

    exposed_total = exposed_pos + exposed_neg
    control_total = control_pos + control_neg
    exposed_rate = exposed_pos / exposed_total if exposed_total else 0.0
    control_rate = control_pos / control_total if control_total else 0.0
    lift = (exposed_rate - control_rate) if control_total else None
    lift_pct = round(lift * 100, 1) if lift is not None else None

    return {
        "user_id": user_id,
        "top_people_count": len(top_people),
        "exposed": {"positive": exposed_pos, "negative": exposed_neg, "rate": round(exposed_rate, 3)},
        "control": {"positive": control_pos, "negative": control_neg, "rate": round(control_rate, 3)},
        "lift": lift_pct,
        "effect_direction": "positive" if lift and lift > 0.05 else "negative" if lift and lift < -0.05 else "flat",
        "gating_ready": bool(lift and lift > 0.05 and exposed_total >= 10),
    }
