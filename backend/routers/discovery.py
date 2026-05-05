"""Discovery router: /discover and /sections/*."""
import os
from fastapi import APIRouter, Depends

from core import (
    require_user, get_catalog, movie_matches, movie_score, movie_reason,
    cached_section, apply_user_filters,
)

router = APIRouter(tags=["discovery"])


@router.get("/discover")
async def discover(user: dict = Depends(require_user), limit: int = 20):
    seen = set(
        (user.get("saved") or []) + (user.get("watched") or []) + (user.get("skipped") or []) +
        (user.get("onboarding_rated") or [])
    )
    pool = [m for m in get_catalog() if m["id"] not in seen and movie_matches(m, user)]
    if len(pool) > 500:
        pool.sort(key=lambda m: m.get("popularity", 0), reverse=True)
        pool = pool[:500]
    pool.sort(key=lambda m: movie_score(m, user), reverse=True)
    out = []
    for m in pool[:limit]:
        item = dict(m)
        item["reason"] = movie_reason(m, user)
        out.append(item)
    return out


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
