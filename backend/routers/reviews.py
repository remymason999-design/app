"""Reviews router."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from core import (
    db, require_user, find_movie, ReviewIn, tmdb_client,
)

router = APIRouter(tags=["reviews"])


@router.get("/movies/{movie_id}/reviews")
async def get_reviews(movie_id: str, user: dict = Depends(require_user)):
    m = find_movie(movie_id)
    if not m:
        raise HTTPException(404, "Movie not found")
    user_reviews = []
    async for r in db.user_reviews.find({"movie_id": movie_id}, {"_id": 0}).sort("created_at", -1):
        user_reviews.append(r)
    tmdb_reviews = []
    if m.get("tmdb_id"):
        try:
            tmdb_reviews = await tmdb_client.fetch_tmdb_reviews(m["type"], m["tmdb_id"], limit=5)
        except Exception:
            pass
    summary = {
        "user_count": len(user_reviews),
        "user_avg": round(sum(r["rating"] for r in user_reviews) / len(user_reviews), 1) if user_reviews else None,
        "tmdb_rating": m.get("rating"),
        "tmdb_vote_count": m.get("vote_count"),
    }
    return {"summary": summary, "user": user_reviews, "tmdb": tmdb_reviews}


@router.post("/movies/{movie_id}/reviews")
async def post_review(movie_id: str, payload: ReviewIn, user: dict = Depends(require_user)):
    if payload.movie_id != movie_id:
        raise HTTPException(400, "movie_id mismatch")
    m = find_movie(movie_id)
    if not m:
        raise HTTPException(404, "Movie not found")
    doc = {
        "movie_id": movie_id,
        "user_id": user["user_id"],
        "user_name": user["name"],
        "rating": payload.rating,
        "text": payload.text.strip()[:2000],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.user_reviews.update_one(
        {"movie_id": movie_id, "user_id": user["user_id"]},
        {"$set": doc},
        upsert=True,
    )
    return doc
