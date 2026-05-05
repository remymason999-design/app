"""User router: preferences, actions, watchlist, watched, services, genres, progress."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from core import (
    db, require_user, clean_user,
    PreferencesIn, ActionIn, ProgressIn,
    movies_by_ids, find_movie, ACTION_WEIGHTS,
    STREAMING_SERVICES, GENRES,
)
from routers.insights import invalidate_insights_cache

router = APIRouter(tags=["user"])


@router.get("/services")
async def services():
    return STREAMING_SERVICES


@router.get("/genres")
async def list_genres():
    return GENRES


@router.put("/user/preferences")
async def set_prefs(payload: PreferencesIn, user: dict = Depends(require_user)):
    update = {}
    if payload.services is not None:
        update["subscriptions"] = payload.services
    if payload.genres is not None:
        update["genres"] = payload.genres
    if payload.excluded_categories is not None:
        update["excluded_categories"] = payload.excluded_categories
    if payload.country is not None:
        update["country"] = payload.country.upper()[:2]
    if payload.age is not None:
        update["age"] = max(1, min(120, payload.age))
    if update:
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return clean_user(fresh)


@router.post("/user/action")
async def user_action(payload: ActionIn, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")
    field_map = {"save": "saved", "skip": "skipped", "watched": "watched"}
    uid = user["user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    if payload.action == "unsave":
        await db.users.update_one({"user_id": uid}, {"$pull": {"saved": payload.movie_id}})
    else:
        field = field_map[payload.action]
        await db.users.update_one(
            {"user_id": uid},
            {"$addToSet": {field: payload.movie_id},
             "$pull": {f: payload.movie_id for f in ["saved", "skipped", "watched"] if f != field},
             "$set": {"last_action_at": now_iso}},
        )
        delta = ACTION_WEIGHTS.get(payload.action, 0)
        if delta:
            inc = {f"genre_weights.{g}": delta for g in movie.get("genres", [])}
            inc[f"type_weights.{movie.get('type','movie')}"] = delta
            if inc:
                await db.users.update_one({"user_id": uid}, {"$inc": inc})
        # Audit trail for analytics + repetition control
        await db.user_actions.insert_one({
            "user_id": uid, "movie_id": payload.movie_id, "action": payload.action,
            "created_at": now_iso,
        })
        if payload.action == "watched":
            invalidate_insights_cache(uid)
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    return clean_user(fresh)


@router.post("/user/progress")
async def set_progress(payload: ProgressIn, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if movie and movie.get("type") == "tv" and movie.get("seasons"):
        season_obj = next((s for s in movie["seasons"] if s.get("season_number") == payload.season), None)
        if not season_obj:
            raise HTTPException(400, f"Season {payload.season} not found")
        max_ep = season_obj.get("episode_count") or 999
        if payload.episode > max_ep:
            raise HTTPException(400, f"Episode exceeds season max ({max_ep})")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {f"progress.{payload.movie_id}": {
            "season": payload.season, "episode": payload.episode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }}},
    )
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return clean_user(fresh)


@router.get("/watchlist")
async def watchlist(user: dict = Depends(require_user)):
    return movies_by_ids(user.get("saved") or [])


@router.get("/watched")
async def watched(user: dict = Depends(require_user)):
    return movies_by_ids(user.get("watched") or [])
