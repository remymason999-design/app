"""Subscription Value Insights router.

Computes per-platform usage and cost-per-watch for the current calendar month
based on the user's `watched` actions logged in `db.user_actions`.

Cached in-memory per user for 1 hour to keep request cost low under 100k+ users.
"""
from datetime import datetime, timezone
from typing import Optional
import time

from fastapi import APIRouter, Depends

from core import (
    db, require_user, get_catalog, STREAMING_SERVICES,
)

router = APIRouter(tags=["insights"])

# user_id -> (computed_at_ts, payload)
_INSIGHTS_CACHE: dict = {}
_INSIGHTS_TTL = 3600  # 1 hour


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _verdict(count: int, price: float) -> dict:
    """Return {tone, headline, message} based on monthly watch count."""
    if count == 0:
        return {
            "tone": "low",
            "headline": "Not used this month",
            "message": f"You haven't watched anything here this month — cancelling could save £{price:.2f}/mo.",
        }
    if count <= 2:
        return {
            "tone": "low",
            "headline": "Low usage",
            "message": f"Only {count} title{'s' if count != 1 else ''} this month — consider rotating to save £{price:.2f}/mo.",
        }
    if count <= 4:
        return {
            "tone": "ok",
            "headline": "Decent value",
            "message": f"{count} titles this month. Solid use of your subscription.",
        }
    return {
        "tone": "great",
        "headline": "Great value",
        "message": f"{count} titles this month — you're getting your money's worth.",
    }


@router.get("/insights/subscriptions")
async def subscription_insights(
    user: dict = Depends(require_user),
    refresh: Optional[int] = 0,
):
    """Per-subscription value insights for the current calendar month.

    Returns:
      {
        currency: "£",
        month_label: "February 2026",
        total_monthly_cost: 32.97,
        total_watched: 7,
        services: [
          {service_id, name, logo_color, price_monthly,
           titles_watched, cost_per_watch, tone, headline, message,
           top_titles: [...]}
        ],
        unused_services: [service_id, ...],
        potential_savings: 9.99,
        cached_at: iso,
      }
    """
    uid = user["user_id"]
    now = datetime.now(timezone.utc)

    # Cache hit
    cached = _INSIGHTS_CACHE.get(uid)
    if cached and not refresh and (time.time() - cached[0]) < _INSIGHTS_TTL:
        return cached[1]

    subs = user.get("subscriptions") or []
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}

    month_start = _start_of_month(now)
    month_start_iso = month_start.isoformat()

    # Pull this month's "watched" actions from the audit log
    cursor = db.user_actions.find(
        {"user_id": uid, "action": "watched", "created_at": {"$gte": month_start_iso}},
        {"_id": 0, "movie_id": 1, "created_at": 1},
    )
    watched_rows = await cursor.to_list(length=5000)
    watched_ids = [r["movie_id"] for r in watched_rows]

    # Resolve catalog entries (single pass)
    catalog_by_id = {m["id"]: m for m in get_catalog()}
    watched_movies = [catalog_by_id[mid] for mid in watched_ids if mid in catalog_by_id]

    services_out = []
    unused = []
    total_watched = 0

    for sid in subs:
        svc = services_by_id.get(sid)
        if not svc:
            continue
        on_this = [m for m in watched_movies if sid in (m.get("available_on") or [])]
        count = len(on_this)
        total_watched += count
        price = float(svc.get("price_monthly", 0) or 0)
        cost_per_watch = round(price / count, 2) if count else None
        verdict = _verdict(count, price)
        if count == 0:
            unused.append(sid)
        # Highlight 4 highest-rated watched titles for this service
        top = sorted(on_this, key=lambda x: x.get("rating", 0), reverse=True)[:4]
        services_out.append({
            "service_id": sid,
            "name": svc["name"],
            "logo_color": svc["logo_color"],
            "price_monthly": price,
            "titles_watched": count,
            "cost_per_watch": cost_per_watch,
            "tone": verdict["tone"],
            "headline": verdict["headline"],
            "message": verdict["message"],
            "top_titles": [
                {"id": m["id"], "title": m["title"], "poster_url": m.get("poster_url")}
                for m in top
            ],
        })

    # Sort: unused first (actionable), then by cost_per_watch desc (worst value first)
    services_out.sort(
        key=lambda r: (
            r["titles_watched"] != 0,                # 0 = unused → top
            -(r["cost_per_watch"] or 0),             # higher cost-per-watch = worse value
        )
    )

    total_cost = sum(s["price_monthly"] for s in services_out)
    potential_savings = round(
        sum(s["price_monthly"] for s in services_out if s["titles_watched"] == 0),
        2,
    )

    payload = {
        "currency": "£",
        "month_label": now.strftime("%B %Y"),
        "total_monthly_cost": round(total_cost, 2),
        "total_watched": total_watched,
        "services": services_out,
        "unused_services": unused,
        "potential_savings": potential_savings,
        "cached_at": now.isoformat(),
    }
    _INSIGHTS_CACHE[uid] = (time.time(), payload)
    return payload


def invalidate_insights_cache(user_id: str) -> None:
    """Drop a user's cached insights — call after a new watched action."""
    _INSIGHTS_CACHE.pop(user_id, None)
