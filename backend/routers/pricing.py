"""Pricing router — public plan listings + admin plan management.

All pricing is UK (region GB, currency GBP). Plans live in the Mongo
``streaming_plans`` collection, seeded from backend/pricing.py on startup.
Admin writes flag rows ``admin_modified: True`` (and ``seed_managed: False``)
so they survive future seed passes.

Public:
  GET /pricing/plans?service_id=   → active plans (optionally one service)
  GET /pricing/services            → active UK services with plans nested

Admin (require_admin):
  POST   /admin/pricing/plans                    → add a plan (or promo row)
  PATCH  /admin/pricing/plans/{id}               → edit fields
  POST   /admin/pricing/plans/{id}/deactivate    → set active=False
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Literal, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import db, require_admin, STREAMING_SERVICES

router = APIRouter(tags=["pricing"])

_VALID_SERVICE_IDS = {s["id"] for s in STREAMING_SERVICES}
_BILLING_TYPES = {"monthly", "annual", "free", "licence_required"}


def _clean(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Public endpoints ────────────────────────────────────────────────────────
@router.get("/pricing/plans")
async def list_plans(service_id: Optional[str] = Query(default=None)):
    """Active plans, optionally filtered to one service. Public (auth ok)."""
    query: dict = {"active": True, "region": "GB"}
    if service_id:
        query["service_id"] = service_id
    plans = await db.streaming_plans.find(query, {"_id": 0}).to_list(length=2000)
    # Stable ordering: service, then monthly price ascending.
    plans.sort(key=lambda p: (p.get("service_id", ""), float(p.get("monthly_price") or 0)))
    return {"plans": plans, "region": "GB", "currency": "GBP"}


@router.get("/pricing/services")
async def services_with_plans():
    """UK-selectable services with their active plans nested.

    Used by onboarding / profile plan selectors. Excludes US-only services
    (active=False) from the STREAMING_SERVICES registry.
    """
    plans = await db.streaming_plans.find(
        {"active": True, "region": "GB"}, {"_id": 0}
    ).to_list(length=2000)
    by_service: dict = {}
    for p in plans:
        by_service.setdefault(p["service_id"], []).append(p)
    for sid in by_service:
        by_service[sid].sort(key=lambda p: float(p.get("monthly_price") or 0))

    out: List[dict] = []
    for svc in STREAMING_SERVICES:
        if svc.get("active") is False or svc.get("us_only"):
            continue
        out.append({
            "id": svc["id"],
            "name": svc["name"],
            "logo_color": svc.get("logo_color"),
            "logo_path": svc.get("logo_path"),
            "price_monthly": svc.get("price_monthly", 0),
            "plans": by_service.get(svc["id"], []),
        })
    return {"services": out, "region": "GB", "currency": "GBP"}


# ── Admin models ──────────────────────────────────────────────────────────
class PlanCreateIn(BaseModel):
    service_id: str
    name: str = Field(min_length=1, max_length=120)
    monthly_price: float = Field(ge=0)
    annual_price: Optional[float] = Field(default=None, ge=0)
    billing_type: Literal["monthly", "annual", "free", "licence_required"] = "monthly"
    has_ads: bool = False
    video_quality: str = "1080p"
    simultaneous_streams: int = Field(default=1, ge=0, le=20)
    minimum_term_months: int = Field(default=0, ge=0, le=36)
    active: bool = True
    source_url: str = ""
    price_verified_at: Optional[str] = None
    is_promo: bool = False
    promo_ends: Optional[str] = None
    addon: bool = False
    id: Optional[str] = None  # optional explicit id


class PlanPatchIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    monthly_price: Optional[float] = Field(default=None, ge=0)
    annual_price: Optional[float] = Field(default=None, ge=0)
    billing_type: Optional[Literal["monthly", "annual", "free", "licence_required"]] = None
    has_ads: Optional[bool] = None
    video_quality: Optional[str] = None
    simultaneous_streams: Optional[int] = Field(default=None, ge=0, le=20)
    minimum_term_months: Optional[int] = Field(default=None, ge=0, le=36)
    active: Optional[bool] = None
    source_url: Optional[str] = None
    price_verified_at: Optional[str] = None
    is_promo: Optional[bool] = None
    promo_ends: Optional[str] = None
    addon: Optional[bool] = None


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# ── Admin endpoints ────────────────────────────────────────────────────────
@router.post("/admin/pricing/plans")
async def admin_add_plan(payload: PlanCreateIn, admin: dict = Depends(require_admin)):
    if payload.service_id not in _VALID_SERVICE_IDS:
        raise HTTPException(400, f"Unknown service_id: {payload.service_id}")

    plan_id = payload.id or f"{payload.service_id}_{_slugify(payload.name)}"
    # Guarantee uniqueness for admin-added rows (e.g. multiple promos).
    if await db.streaming_plans.find_one({"id": plan_id}):
        plan_id = f"{plan_id}_{uuid.uuid4().hex[:6]}"

    doc = {
        "id": plan_id,
        "service_id": payload.service_id,
        "name": payload.name,
        "monthly_price": float(payload.monthly_price),
        "annual_price": (float(payload.annual_price) if payload.annual_price is not None else None),
        "billing_type": payload.billing_type,
        "has_ads": bool(payload.has_ads),
        "video_quality": payload.video_quality,
        "simultaneous_streams": int(payload.simultaneous_streams),
        "minimum_term_months": int(payload.minimum_term_months),
        "active": bool(payload.active),
        "region": "GB",
        "source_url": payload.source_url or "",
        "price_verified_at": payload.price_verified_at or _today(),
        "is_promo": bool(payload.is_promo),
        "promo_ends": payload.promo_ends,
        "addon": bool(payload.addon),
        # Admin-created → never seed-managed; survives seeding untouched.
        "seed_managed": False,
        "admin_modified": True,
        "created_by": admin.get("user_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.streaming_plans.insert_one(dict(doc))
    return _clean(doc)


@router.patch("/admin/pricing/plans/{plan_id}")
async def admin_edit_plan(plan_id: str, payload: PlanPatchIn, admin: dict = Depends(require_admin)):
    existing = await db.streaming_plans.find_one({"id": plan_id})
    if not existing:
        raise HTTPException(404, "Plan not found")

    fields = payload.model_dump(exclude_unset=True)
    if "billing_type" in fields and fields["billing_type"] not in _BILLING_TYPES:
        raise HTTPException(400, "Invalid billing_type")

    update = dict(fields)
    # Any admin write marks the row as admin-modified so future seed passes
    # never overwrite it, and stamps a fresh verification date unless the admin
    # explicitly supplied one.
    update["admin_modified"] = True
    update["seed_managed"] = False
    if "price_verified_at" not in update:
        update["price_verified_at"] = _today()
    update["updated_by"] = admin.get("user_id")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.streaming_plans.update_one({"id": plan_id}, {"$set": update})
    fresh = await db.streaming_plans.find_one({"id": plan_id}, {"_id": 0})
    return fresh


@router.post("/admin/pricing/plans/{plan_id}/deactivate")
async def admin_deactivate_plan(plan_id: str, admin: dict = Depends(require_admin)):
    existing = await db.streaming_plans.find_one({"id": plan_id})
    if not existing:
        raise HTTPException(404, "Plan not found")
    await db.streaming_plans.update_one(
        {"id": plan_id},
        {"$set": {
            "active": False,
            "admin_modified": True,
            "seed_managed": False,
            "updated_by": admin.get("user_id"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    fresh = await db.streaming_plans.find_one({"id": plan_id}, {"_id": 0})
    return fresh
