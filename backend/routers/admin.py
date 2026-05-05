"""Admin router."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException

from core import db, require_admin, get_catalog, refresh_catalog_from_tmdb, logger

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/refresh-catalog")
async def admin_refresh_catalog(user: dict = Depends(require_admin), pages: int = 8):
    try:
        n = await refresh_catalog_from_tmdb(pages=pages)
        return {"ok": True, "count": n}
    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        raise HTTPException(502, f"TMDB refresh failed: {e}")


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

    # Swipe distribution
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
