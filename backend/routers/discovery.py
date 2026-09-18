"""Discovery router: /discover, /sections/*, and engine engagement summary.

Strict invariants applied to every list endpoint:
  1. User filters (subscriptions, content_type, excluded_categories,
     excluded_genres) run BEFORE any ranking/sorting.
  2. Items the user has saved/watched/skipped/onboarding_rated are stripped.
  3. Recently shown items (LRU on user doc) are stripped.
"""
import os
import time
from typing import Optional
from fastapi import APIRouter, Depends, Query

from core import (
    require_user, cached_section, apply_user_filters, catalog_quality_gate,
)
from engine import build_feed, engagement_summary, _recently_shown_active

router = APIRouter(tags=["discovery"])


# ── Per-user /discover cache ─────────────────────────────────────────────────
# build_feed scores the entire catalog against user weights — heavy work that
# should not repeat every time the SPA refills or the user navigates back to
# Discover. We cache the built feed keyed by (user_id, limit, toggle flags) for
# a short TTL and invalidate explicitly whenever the user's preferences/state
# change (POST /user/action, PUT /user/preferences) via invalidate_discover_cache.
_DISCOVER_CACHE: dict = {}
_DISCOVER_TTL = 60.0  # seconds — short window so swipes still feel responsive


def invalidate_discover_cache(user_id: str) -> None:
    """Drop every cached feed for this user. Cheap O(N) over a small dict."""
    if not user_id:
        return
    for k in [k for k in _DISCOVER_CACHE if k[0] == user_id]:
        _DISCOVER_CACHE.pop(k, None)


def _cache_get(key: tuple):
    entry = _DISCOVER_CACHE.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _DISCOVER_TTL:
        _DISCOVER_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value) -> None:
    _DISCOVER_CACHE[key] = (time.time(), value)
    # Soft cap to prevent unbounded growth in pathological cases.
    if len(_DISCOVER_CACHE) > 5000:
        # Drop the oldest 1000 entries.
        for k in sorted(_DISCOVER_CACHE.keys(), key=lambda k: _DISCOVER_CACHE[k][0])[:1000]:
            _DISCOVER_CACHE.pop(k, None)


def _strip_seen(items: list, user: dict) -> list:
    """Remove anything the user has already touched + the recently-shown LRU."""
    seen = set(
        (user.get("saved") or []) +
        (user.get("watched") or []) +
        (user.get("skipped") or []) +
        (user.get("onboarding_rated") or [])
    )
    seen |= _recently_shown_active(user)
    if not seen:
        return items
    return [m for m in items if m.get("id") not in seen]


def _section(items: list, user: dict, limit: int) -> list:
    """Quality gate → apply filters → strip seen → sort by popularity → trim."""
    _region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = [m for m in items if catalog_quality_gate(m, user_region=_region, user=user)]
    items = apply_user_filters(items, user)
    items = _strip_seen(items, user)
    items.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return items[:limit]


@router.get("/discover")
async def discover(
    user: dict = Depends(require_user),
    limit: int = 20,
    content_type: Optional[str] = Query(None, description="Restrict feed to 'movie' or 'tv' only (powers Movies/TV Shows tabs)"),
    include_other_services: bool = Query(False, description="User opt-in: show titles from all streaming services"),
    include_rent_buy: bool = Query(False, description="User opt-in: include rent/buy titles alongside subscriptions"),
):
    ct = content_type if content_type in ("movie", "tv") else None
    cache_key = (user["user_id"], int(limit), bool(include_other_services), bool(include_rent_buy), ct)
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit
    # An explicit tab-level content_type overrides the user's stored preference
    # so the Movies / TV Shows tabs always return that type, while For You
    # (ct=None) honours whatever the user has saved.
    feed_user = {**user, "content_type": ct} if ct else user
    feed = await build_feed(
        feed_user, limit=limit,
        include_other_services=include_other_services,
        include_rent_buy=include_rent_buy,
    )
    _cache_put(cache_key, feed)
    return feed


@router.get("/discover/debug")
async def discover_debug(
    user: dict = Depends(require_user),
    limit: int = 20,
    include_other_services: bool = Query(False),
    include_rent_buy: bool = Query(False),
):
    """Debug endpoint: full breakdown of genre intent + rotation decisions.

    meta fields:
      selected_genres          — genres from onboarding
      pool_total               — candidates after all filters
      intent_pool_count        — titles matching selected genres
      fill_pool_count          — titles not matching selected genres
      intent_slots/fill_slots  — how output was composed
      intent_low_pool_warning  — True if intent pool < 10 titles
      recently_shown_excluded  — titles suppressed by 72h cooldown
      permanently_excluded     — titles in saved/watched/skipped/rated
      cooldown_hours           — current cooldown window (72h)
      tracking_max             — max recently_shown entries tracked (400)

    feed card fields:
      slot_type    — "intent" (matches selected genre) or "fill"
      rating_band  — "excellent" (≥8.0) / "good" (≥7.0) / "decent"
      score        — hybrid score used for ranking within each band
      fill_reason  — why a non-intent title was included (fill cards only)
    """
    feed = await build_feed(
        user, limit=limit,
        include_other_services=include_other_services,
        include_rent_buy=include_rent_buy,
    )
    if not feed:
        return {"meta": {}, "feed": []}

    first_signals = feed[0].get("_signals", {})
    meta = first_signals.get("feed_meta", {})

    band_counts: dict = {}
    slot_counts: dict = {}
    items = []
    for card in feed:
        sigs = card.get("_signals", {})
        band = sigs.get("rating_band", "unknown")
        slot = sigs.get("intent_slot", "core")
        band_counts[band] = band_counts.get(band, 0) + 1
        slot_counts[slot] = slot_counts.get(slot, 0) + 1
        items.append({
            "title":          card.get("title"),
            "year":           card.get("year"),
            "genres":         card.get("genres"),
            "rating":         card.get("rating"),
            "popularity":     card.get("popularity"),
            "vote_count":     card.get("vote_count"),
            "type":           card.get("type"),
            "slot_type":      slot,
            "rating_band":    band,
            "score":          sigs.get("score"),
            "variety_reason": sigs.get("variety_reason"),
            "fill_reason":    sigs.get("fill_reason"),
            "reason":         card.get("reason"),
            # ── Per-recommendation explainability ───────────────────────────
            "why_shown":           sigs.get("why_shown", card.get("reason")),
            "is_wildcard":         sigs.get("is_wildcard", slot == "wildcard"),
            "is_fallback":         sigs.get("is_fallback", False),
            "provider_confidence": sigs.get("provider_confidence"),
        })

    return {
        "meta": {
            **meta,
            "band_distribution":    band_counts,
            "slot_distribution":    slot_counts,
            "eligible_pool_size":   meta.get("eligible_pool_size", meta.get("pool_total")),
            "core_pool_count":      meta.get("core_pool_count"),
            "adjacent_pool_count":  meta.get("adjacent_pool_count"),
            "wildcard_pool_count":  meta.get("wildcard_pool_count"),
            "adjacent_genres":      meta.get("adjacent_genres", []),
            "exploration_weight":   meta.get("exploration_weight"),
            "exploration_ratios":   meta.get("exploration_ratios"),
            "queue_size":           meta.get("queue_size", len(items)),
            "shown_excluded":       meta.get("shown_excluded", meta.get("recently_shown_excluded", 0)),
            "permanently_excluded": meta.get("permanently_excluded", 0),
            "next_refill_at_pool":  (meta.get("pool_total", 0) or 0) - (meta.get("queue_size", len(items)) or 0),
            # ── Final-polish diagnostics (passthrough from feed_meta) ────────
            "pool_before_filters":       meta.get("pool_before_filters"),
            "pool_after_filters":        meta.get("pool_after_filters"),
            "pool_after_broadening":     meta.get("pool_after_broadening"),
            "reality_suppressed_count":  meta.get("reality_suppressed_count"),
            "reality_allowed":           meta.get("reality_allowed"),
            "low_vote_suppressed_count": meta.get("low_vote_suppressed_count"),
            "genre_match_mode":          meta.get("genre_match_mode"),
            "fallback_count":            meta.get("fallback_count"),
            "provider_confidence_distribution": meta.get("provider_confidence_distribution"),
            "rejection_debug":           meta.get("rejection_debug"),
        },
        "feed": items,
    }


def _effective_user(
    user: dict,
    include_other_services: bool,
    include_rent_buy: bool,
) -> dict:
    """Apply Discover toggles consistently across all section endpoints.

    The toggles relax the subscription filter exactly the same way as on
    /discover, so trending/upcoming/popular never feel stricter than the main feed.
    """
    if not (include_other_services or include_rent_buy):
        return user
    u = dict(user)
    if include_other_services:
        # Drop subscriptions filter entirely — show titles on any streaming service.
        u["subscriptions"] = []
        u["_relax_subs"] = True
    if include_rent_buy:
        u["_include_rent_buy"] = True
    return u


@router.get("/sections/upcoming")
async def section_upcoming(
    user: dict = Depends(require_user),
    limit: int = 30,
    include_other_services: bool = Query(False),
    include_rent_buy: bool = Query(False),
):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = await cached_section("/movie/upcoming", "movie", region)
    return _section(items, _effective_user(user, include_other_services, include_rent_buy), limit)


@router.get("/sections/trending")
async def section_trending(
    user: dict = Depends(require_user),
    limit: int = 30,
    include_other_services: bool = Query(False),
    include_rent_buy: bool = Query(False),
):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = []
    for kind in ("movie", "tv"):
        items.extend(await cached_section(f"/trending/{kind}/week", kind, region))
    return _section(items, _effective_user(user, include_other_services, include_rent_buy), limit)


@router.get("/sections/popular-locally")
async def section_popular_locally(
    user: dict = Depends(require_user),
    limit: int = 30,
    include_other_services: bool = Query(False),
    include_rent_buy: bool = Query(False),
):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = await cached_section("/movie/popular", "movie", region)
    return _section(items, _effective_user(user, include_other_services, include_rent_buy), limit)


@router.get("/me/engagement")
async def me_engagement(user: dict = Depends(require_user)):
    """Transparency endpoint — what the engine knows about me right now."""
    return await engagement_summary(user)
