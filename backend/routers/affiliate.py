"""Affiliate tracking + admin CSV export."""
import io
import csv
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import db, require_user, require_admin, find_movie, STREAMING_SERVICES
from monetization import MONETIZATION_FLAGS

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


def build_affiliate_url(base_url: str, user_id: str, movie_id: str, service_id: str) -> str:
    """Add only WatchSmart campaign parameters when tracking is enabled.

    The user ID is deliberately not sent to third parties.  ``user_id`` stays
    in this compatibility-preserving signature for callers/tests that already
    use the helper.
    """
    parsed = urlparse(base_url)
    # Preserve all legitimate provider parameters, including duplicate keys.
    # Replace only the campaign keys WatchSmart owns.
    owned = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "ref"}
    existing = [
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in owned
    ]
    existing.extend([
        ("utm_source", "watchsmart"),
        ("utm_medium", "referral"),
        ("utm_campaign", "where-to-watch"),
        ("utm_content", f"{service_id}:{movie_id}"),
        ("ref", "watchsmart"),
    ])
    return urlunparse(parsed._replace(query=urlencode(existing)))


class AffiliateClickIn(BaseModel):
    movie_id: str
    service_id: str
    destination_type: str = Field(default="stream", max_length=20)
    source_screen: str = Field(default="movie_detail", max_length=40)
    campaign_id: str | None = Field(default=None, max_length=120)
    partner_id: str | None = Field(default=None, max_length=120)


@router.post("/click")
async def affiliate_click(payload: AffiliateClickIn, request: Request, user: dict = Depends(require_user)):
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    svc = services_by_id.get(payload.service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    movie = find_movie(payload.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")
    if payload.destination_type not in {"stream", "rent", "buy", "subscription", "partner"}:
        raise HTTPException(422, "Invalid destination type")
    if payload.source_screen.strip().lower() not in {
        "movie_detail", "search", "discover", "watchlist", "savings", "unknown"
    }:
        raise HTTPException(422, "Invalid source screen")
    base_url = svc.get("affiliate_url") or ""
    if urlparse(base_url).scheme not in {"http", "https"} or not urlparse(base_url).netloc:
        raise HTTPException(502, "Provider destination is unavailable")

    tracking_enabled = bool(MONETIZATION_FLAGS["affiliate_tracking_enabled"])
    destination = (
        build_affiliate_url(base_url, user["user_id"], movie["id"], svc["id"])
        if tracking_enabled else base_url
    )
    if tracking_enabled:
        row = {
            "user_id": user["user_id"],
            "title_id": movie["id"],
            "movie_id": movie["id"],  # historical field compatibility
            "movie_title": movie["title"],
            "provider": svc["id"],
            "service_id": svc["id"],  # historical field compatibility
            "service_name": svc["name"],
            "destination_type": payload.destination_type,
            "base_url": base_url,
            "tracked_url": destination,
            "source_screen": payload.source_screen.strip().lower(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if payload.campaign_id:
            row["campaign_id"] = payload.campaign_id.strip()
        if payload.partner_id:
            row["partner_id"] = payload.partner_id.strip()
        await db.affiliate_clicks.insert_one(row)
    return {"url": destination}


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
