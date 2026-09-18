"""Savings + Watchlist value router."""
from fastapi import APIRouter, Depends

from core import (
    require_user, get_catalog, movies_by_ids, STREAMING_SERVICES, db,
)

router = APIRouter(tags=["savings"])


async def _plan_price_index() -> dict:
    """Map plan_id → plan doc (active GB plans) for effective-cost lookups."""
    plans = await db.streaming_plans.find(
        {"region": "GB"}, {"_id": 0}
    ).to_list(length=2000)
    return {p["id"]: p for p in plans}


def _cheapest_standard_price(service_id: str, plans_by_id: dict) -> tuple:
    """Return (price, plan_name) for the cheapest standard paid plan of a service.

    Standard = active, not promo, not add-on, not free/licence, price > 0.
    Falls back to the service registry price_monthly when no plan doc exists.
    """
    candidates = [
        p for p in plans_by_id.values()
        if p.get("service_id") == service_id
        and p.get("active")
        and not p.get("is_promo")
        and not p.get("addon")
        and p.get("billing_type") not in ("free", "licence_required")
        and float(p.get("monthly_price") or 0) > 0
    ]
    if candidates:
        best = min(candidates, key=lambda p: float(p["monthly_price"]))
        return float(best["monthly_price"]), best.get("name")
    svc = next((s for s in STREAMING_SERVICES if s["id"] == service_id), None)
    return (float(svc.get("price_monthly", 0)) if svc else 0.0), None


@router.get("/savings")
async def savings(user: dict = Depends(require_user)):
    subs = user.get("subscriptions") or []
    services_by_id = {s["id"]: s for s in STREAMING_SERVICES}
    sub_plans = user.get("subscription_plans") or {}
    plans_by_id = await _plan_price_index()
    activity_ids = (user.get("saved") or []) + (user.get("watched") or [])
    activity = movies_by_ids(activity_ids)

    def _effective_for(sid: str) -> tuple:
        """Return (monthly_cost, plan_name, billing_cycle) for a subscribed service.

        Priority:
          1. subscription_plans[sid].effective_monthly_cost (custom or derived)
          2. cheapest standard plan price for the service
          3. free / licence_required services contribute £0 unless the user
             entered a custom price.
        effective_monthly_cost is always a MONTHLY figure (annual billing is
        stored as annual/12 by the client), so total_yearly = monthly × 12.
        """
        entry = sub_plans.get(sid) or {}
        chosen_plan = plans_by_id.get(entry.get("plan_id")) if entry.get("plan_id") else None
        billing_cycle = entry.get("billing_cycle") or "monthly"
        # 1. Explicit effective cost (custom price OR client-derived).
        if entry.get("effective_monthly_cost") is not None:
            name = chosen_plan.get("name") if chosen_plan else None
            return float(entry["effective_monthly_cost"]), name, billing_cycle
        # 2. Derive from the chosen plan.
        if chosen_plan:
            if billing_cycle == "annual" and chosen_plan.get("annual_price"):
                return round(float(chosen_plan["annual_price"]) / 12.0, 2), chosen_plan.get("name"), "annual"
            bt = chosen_plan.get("billing_type")
            if bt in ("free", "licence_required") and not entry.get("custom_price"):
                return 0.0, chosen_plan.get("name"), billing_cycle
            return float(chosen_plan.get("monthly_price") or 0), chosen_plan.get("name"), billing_cycle
        # 3. Fallback: cheapest standard plan price.
        price, name = _cheapest_standard_price(sid, plans_by_id)
        return price, name, "monthly"

    total = 0.0
    usage = []
    for sid in subs:
        svc = services_by_id.get(sid)
        if not svc:
            continue
        monthly_cost, plan_name, billing_cycle = _effective_for(sid)
        total += monthly_cost
        count = sum(1 for m in activity if sid in m.get("available_on", []))
        seen = set(activity_ids + (user.get("skipped") or []))
        avail_unseen = sum(
            1 for m in get_catalog()
            if sid in m.get("available_on", []) and m["id"] not in seen
        )
        usage.append({
            "service_id": sid, "name": svc["name"], "logo_color": svc["logo_color"],
            # Backward-compat: price_monthly now reflects the user's effective
            # monthly cost for this service (was the flat registry price).
            "price_monthly": round(monthly_cost, 2),
            "plan_name": plan_name,
            "monthly_cost": round(monthly_cost, 2),
            "billing_cycle": billing_cycle,
            # True when the user has not explicitly confirmed a plan for this
            # service (mobile shows a "confirm your plan" prompt).
            "needs_plan": sid not in sub_plans,
            "activity_count": count, "available_unseen": avail_unseen,
        })
    usage.sort(key=lambda x: x["activity_count"])

    suggestions = []
    if len(usage) >= 2:
        worst = usage[0]
        if worst["activity_count"] <= 1:
            suggestions.append({
                "type": "cancel", "service_id": worst["service_id"],
                "headline": f"Cancel {worst['name']} to save £{worst['price_monthly']:.2f}/mo",
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
                f"With {len(subs)} services at £{total:.2f}/mo, rotate one in/out each month "
                f"to save up to £{(total/len(subs)):.2f}/mo."
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
