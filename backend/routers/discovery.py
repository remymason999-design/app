"""Discovery router: /discover, /sections/*, and engine engagement summary."""
import os
from fastapi import APIRouter, Depends

from core import (
    require_user, cached_section, apply_user_filters,
)
from engine import build_feed, engagement_summary

router = APIRouter(tags=["discovery"])


@router.get("/discover")
async def discover(user: dict = Depends(require_user), limit: int = 20):
    return await build_feed(user, limit=limit)


@router.get("/sections/upcoming")
async def section_upcoming(user: dict = Depends(require_user), limit: int = 12):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = await cached_section("/movie/upcoming", "movie", region)
    items = apply_user_filters(items, user)
    items.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return items[:limit]


@router.get("/sections/trending")
async def section_trending(user: dict = Depends(require_user), limit: int = 12):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = []
    for kind in ("movie", "tv"):
        items.extend(await cached_section(f"/trending/{kind}/week", kind, region))
    items = apply_user_filters(items, user)
    items.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return items[:limit]


@router.get("/sections/popular-locally")
async def section_popular_locally(user: dict = Depends(require_user), limit: int = 12):
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    items = await cached_section("/movie/popular", "movie", region)
    items = apply_user_filters(items, user)
    items.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return items[:limit]


@router.get("/me/engagement")
async def me_engagement(user: dict = Depends(require_user)):
    """Transparency endpoint — what the engine knows about me right now."""
    return await engagement_summary(user)
