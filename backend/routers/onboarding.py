"""Onboarding router.

Exposes three endpoints used by the 4-step onboarding flow:

  GET  /onboarding/titles   -> 15-20 diverse, popular titles (mix of genres,
                               eras, and both movies + TV) for the "Rate these"
                               step. Excludes anything the user has already
                               touched or rated during onboarding.

  POST /onboarding/rate     -> records a like / dislike / skip for a title,
                               updates genre_weights + type_weights live, and
                               adds the movie to user.onboarding_rated so it
                               never reappears in Discover.

  POST /onboarding/complete -> marks onboarding_completed = true.
"""
import random
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import db, require_user, get_catalog, find_movie, clean_user

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

ONBOARD_WEIGHTS = {"like": 3, "dislike": -2, "skip": 0}


class RateIn(BaseModel):
    movie_id: str
    rating: Literal["like", "dislike", "skip"]


def _pick_diverse_titles(n: int = 18, seen: set = None) -> list:
    """Pick n titles — one per genre/era when possible, covering movies + TV.

    Strategy: score every catalog entry by popularity + rating, then walk down
    the sorted list greedily, keeping at most 2 per (primary_genre, type)
    bucket to force variety.
    """
    seen = seen or set()
    ranked = sorted(
        (m for m in get_catalog() if m["id"] not in seen and m.get("poster_url")),
        key=lambda m: (m.get("popularity") or 0) * (m.get("rating") or 7),
        reverse=True,
    )
    buckets: dict = {}
    chosen: list = []
    for m in ranked:
        primary_genre = (m.get("genres") or ["Other"])[0]
        key = (primary_genre, m.get("type") or "movie")
        if buckets.get(key, 0) >= 2:
            continue
        buckets[key] = buckets.get(key, 0) + 1
        chosen.append(m)
        if len(chosen) >= n:
            break
    # If we under-filled (small catalog), top up from remaining
    if len(chosen) < n:
        chosen_ids = {c["id"] for c in chosen}
        for m in ranked:
            if m["id"] in chosen_ids:
                continue
            chosen.append(m)
            if len(chosen) >= n:
                break
    random.shuffle(chosen)
    return chosen


@router.get("/titles")
async def onboarding_titles(user: dict = Depends(require_user), limit: int = 18):
    seen = set(
        (user.get("saved") or []) + (user.get("watched") or []) + (user.get("skipped") or []) +
        (user.get("onboarding_rated") or [])
    )
    picks = _pick_diverse_titles(limit, seen=seen)
    return [
        {
            "id": m["id"],
            "title": m["title"],
            "type": m.get("type"),
            "year": m.get("year"),
            "overview": m.get("overview"),
            "poster_url": m.get("poster_url"),
            "backdrop_url": m.get("backdrop_url"),
            "rating": m.get("rating"),
            "genres": (m.get("genres") or [])[:3],
        }
        for m in picks
    ]


@router.post("/rate")
async def onboarding_rate(payload: RateIn, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")
    uid = user["user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    update = {
        "$addToSet": {"onboarding_rated": payload.movie_id},
        "$set": {"last_action_at": now_iso},
    }
    delta = ONBOARD_WEIGHTS.get(payload.rating, 0)
    if delta:
        inc = {f"genre_weights.{g}": delta for g in movie.get("genres", [])}
        inc[f"type_weights.{movie.get('type','movie')}"] = delta
        if inc:
            update["$inc"] = inc
    await db.users.update_one({"user_id": uid}, update)

    # Audit trail (same collection Admin analytics reads)
    await db.user_actions.insert_one({
        "user_id": uid,
        "movie_id": payload.movie_id,
        "action": f"onboard_{payload.rating}",
        "created_at": now_iso,
    })

    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    return {"ok": True, "user": clean_user(fresh)}


@router.post("/complete")
async def onboarding_complete(user: dict = Depends(require_user)):
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "onboarding_completed": True,
            "onboarding_completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return clean_user(fresh)
