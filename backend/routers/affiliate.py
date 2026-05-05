"""Affiliate tracking + admin CSV export."""
import io
import csv
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core import db, require_user, require_admin, ClickIn, find_movie, STREAMING_SERVICES

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


def build_affiliate_url(base_url: str, user_id: str, movie_id: str, service_id: str) -> str:
    parsed = urlparse(base_url)
    existing = dict(parse_qsl(parsed.query))
    existing.update({
        "utm_source": "watchsmart",
        "utm_medium": "referral",
        "utm_campaign": "where-to-watch",
        "utm_content": f"{service_id}:{movie_id}",
        "ref": "watchsmart",
        "sub_id": user_id,
    })
    return urlunparse(parsed._replace(query=urlencode(existing)))


@router.post("/click")
async def affiliate_click(payload: ClickIn, request: Request, user: dict = Depends(require_user)):
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    svc = services_by_id.get(payload.service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    movie = find_movie(payload.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")
    tracked_url = build_affiliate_url(svc["affiliate_url"], user["user_id"], movie["id"], svc["id"])
    await db.affiliate_clicks.insert_one({
        "user_id": user["user_id"],
        "movie_id": movie["id"],
        "movie_title": movie["title"],
        "service_id": svc["id"],
        "service_name": svc["name"],
        "base_url": svc["affiliate_url"],
        "tracked_url": tracked_url,
        "referer": request.headers.get("referer"),
        "user_agent": request.headers.get("user-agent"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"url": tracked_url}


@router.get("/me")
async def affiliate_me(user: dict = Depends(require_user)):
    pipeline = [
        {"$match": {"user_id": user["user_id"]}},
        {"$group": {"_id": "$service_id", "count": {"$sum": 1}, "service_name": {"$first": "$service_name"}}},
        {"$sort": {"count": -1}},
    ]
    per_service = []
    async for row in db.affiliate_clicks.aggregate(pipeline):
        per_service.append({
            "service_id": row["_id"],
            "service_name": row.get("service_name"),
            "count": row["count"],
        })
    total = await db.affiliate_clicks.count_documents({"user_id": user["user_id"]})
    return {"total": total, "per_service": per_service}


@router.get("/stats")
async def affiliate_stats(user: dict = Depends(require_admin)):
    pipeline = [
        {"$group": {
            "_id": "$service_id",
            "count": {"$sum": 1},
            "service_name": {"$first": "$service_name"},
            "unique_users": {"$addToSet": "$user_id"},
        }},
        {"$project": {"service_id": "$_id", "service_name": 1, "count": 1,
                      "unique_users": {"$size": "$unique_users"}, "_id": 0}},
        {"$sort": {"count": -1}},
    ]
    per_service = []
    async for row in db.affiliate_clicks.aggregate(pipeline):
        per_service.append(row)
    total_clicks = await db.affiliate_clicks.count_documents({})
    total_users = len(await db.affiliate_clicks.distinct("user_id"))
    return {"total_clicks": total_clicks, "unique_users": total_users, "per_service": per_service}


@router.get("/export.csv")
async def affiliate_export_csv(user: dict = Depends(require_admin)):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "created_at", "user_id", "service_id", "service_name",
        "movie_id", "movie_title", "tracked_url", "referer", "user_agent",
    ])
    cursor = db.affiliate_clicks.find({}, {"_id": 0}).sort("created_at", -1)
    async for r in cursor:
        writer.writerow([
            r.get("created_at"), r.get("user_id"), r.get("service_id"), r.get("service_name"),
            r.get("movie_id"), r.get("movie_title"), r.get("tracked_url"),
            r.get("referer", ""), r.get("user_agent", ""),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=watchsmart_affiliate_clicks.csv"},
    )
