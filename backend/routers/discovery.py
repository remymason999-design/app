"""Discovery router: /discover, /sections/*, and engine engagement summary.

Strict invariants applied to every list endpoint:
  1. User filters (subscriptions, content_type, excluded_categories,
     excluded_genres) run BEFORE any ranking/sorting.
  2. Items the user has saved/watched/skipped/onboarding_rated are stripped.
  3. Recently shown items (LRU on user doc) are stripped.
"""
import os
from fastapi import APIRouter, Depends

from core import (
    require_user, cached_section, apply_user_filters,
)
from engine import build_feed, engagement_summary, _recently_shown_active

router = APIRouter(tags=["discovery"])


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
    """Apply filters → strip seen → sort by popularity → trim."""
    items = apply_user_filters(items, user)
    items = _strip_seen(items, user)
    items.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return items[:limit]


@router.get("/discover")
async def discover(user: dict = Depends(require_user), limit: int = 20):
    return await build_feed(user, limit=limit)


@router.get("/sections/upcoming")
async def section_upcoming(user: dict = Depends(require_user), limit: int = 12):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = await cached_section("/movie/upcoming", "movie", region)
    return _section(items, user, limit)


@router.get("/sections/trending")
async def section_trending(user: dict = Depends(require_user), limit: int = 12):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = []
    for kind in ("movie", "tv"):
        items.extend(await cached_section(f"/trending/{kind}/week", kind, region))
    return _section(items, user, limit)


@router.get("/sections/popular-locally")
async def section_popular_locally(user: dict = Depends(require_user), limit: int = 12):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = await cached_section("/movie/popular", "movie", region)
    return _section(items, user, limit)


@router.get("/me/engagement")
async def me_engagement(user: dict = Depends(require_user)):
    """Transparency endpoint — what the engine knows about me right now."""
    return await engagement_summary(user)
