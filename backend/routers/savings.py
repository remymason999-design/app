"""Savings + Watchlist value router."""
from fastapi import APIRouter, Depends

from core import (
    require_user, get_catalog, movies_by_ids, STREAMING_SERVICES,
)

router = APIRouter(tags=["savings"])


@router.get("/savings")
async def savings(user: dict = Depends(require_user)):
    subs = user.get("subscriptions") or []
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    total = sum(services_by_id.get(s, {}).get("price_monthly", 0) for s in subs)
    activity_ids = (user.get("saved") or []) + (user.get("watched") or [])
    activity = movies_by_ids(activity_ids)

    usage = []
    for sid in subs:
        svc = services_by_id.get(sid)
        if not svc:
            continue
        count = sum(1 for m in activity if sid in m.get("available_on", []))
        seen = set(activity_ids + (user.get("skipped") or []))
        avail_unseen = sum(
            1 for m in get_catalog()
            if sid in m.get("available_on", []) and m["id"] not in seen
        )
        usage.append({
            "service_id": sid, "name": svc["name"], "logo_color": svc["logo_color"],
            "price_monthly": svc["price_monthly"],
            "activity_count": count, "available_unseen": avail_unseen,
        })
    usage.sort(key=lambda x: x["activity_count"])

    suggestions = []
    if len(usage) >= 2:
        worst = usage[0]
        if worst["activity_count"] <= 1:
            suggestions.append({
                "type": "cancel", "service_id": worst["service_id"],
                "headline": f"Cancel {worst['name']} to save ${worst['price_monthly']:.2f}/mo",
                "reason": (
                    f"You've engaged with only {worst['activity_count']} title(s) on {worst['name']}. "
                    "Most of your activity lives on other services."
                ),
                "monthly_savings": worst["price_monthly"],
            })
    if len(subs) >= 3:
        suggestions.append({
            "type": "rotate",
            "headline": "Rotate subscriptions monthly",
            "reason": (
                f"With {len(subs)} services at ${total:.2f}/mo, rotate one in/out each month "
                f"to save up to ${(total/len(subs)):.2f}/mo."
            ),
            "monthly_savings": round(total / len(subs), 2),
        })

    overlap_titles = sum(1 for m in get_catalog() if len(set(m.get("available_on", [])) & set(subs)) >= 2)

    return {
        "total_monthly": round(total, 2),
        "total_yearly": round(total * 12, 2),
        "subscription_count": len(subs),
        "usage": usage,
        "suggestions": suggestions,
        "overlap_titles": overlap_titles,
    }


@router.get("/watchlist/value")
async def watchlist_value(user: dict = Depends(require_user)):
    activity_ids = (user.get("saved") or []) + (user.get("watched") or [])
    activity = movies_by_ids(activity_ids)
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    subs = user.get("subscriptions") or []
    rows = []
    for sid in services_by_id:
        svc = services_by_id[sid]
        on_this = [m for m in activity if sid in (m.get("available_on") or [])]
        value_score = sum((m.get("rating") or 0) for m in on_this)
        rows.append({
            "service_id": sid, "name": svc["name"], "logo_color": svc["logo_color"],
            "price_monthly": svc["price_monthly"],
            "subscribed": sid in subs,
            "titles_count": len(on_this),
            "value_score": round(value_score, 1),
            "cost_per_title": round(svc["price_monthly"] / len(on_this), 2) if on_this else None,
            "top_titles": [
                {"id": m["id"], "title": m["title"], "poster_url": m.get("poster_url")}
                for m in sorted(on_this, key=lambda x: x.get("rating", 0), reverse=True)[:4]
            ],
        })
    rows.sort(key=lambda r: r["value_score"], reverse=True)
    return {"services": rows, "watchlist_size": len(activity_ids)}
