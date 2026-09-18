"""Central UK subscription-plan pricing data + Mongo seeding.

This module is the single source of truth for UK (region GB, currency GBP)
streaming plan pricing.  It owns:

  * UK_PLANS — a canonical list of plan dicts (see field docs below).
  * seed_pricing_plans() — an idempotent, restart-safe upsert into the
    `streaming_plans` collection that PRESERVES admin edits.
  * helper accessors used by the pricing router and the savings router.

Design rules (why it behaves the way it does):

  * Promos never overwrite standard prices. A promotional price is stored as a
    SEPARATE plan row flagged ``is_promo: True`` (with optional ``promo_ends``).
  * Admin edits survive restarts. Seeding only INSERTS plans that don't exist,
    and only UPDATES docs that are still ``seed_managed: True`` AND have no
    ``admin_modified`` flag. The moment an admin writes to a plan we set
    ``admin_modified: True`` so the seed pass will never clobber it again.
  * Every plan records ``price_verified_at`` and ``source_url`` (the provider's
    official price page) so pricing is auditable and its freshness is visible.

Plan dict fields
----------------
  id                    : stable unique key (also the Mongo doc key)
  service_id            : canonical service id (matches STREAMING_SERVICES)
  name                  : human plan name ("Standard with Ads", ...)
  monthly_price         : float GBP/month (0 for free / licence services)
  annual_price          : float GBP/year, optional (None when N/A)
  billing_type          : "monthly" | "annual" | "free" | "licence_required"
  has_ads               : bool
  video_quality         : str ("1080p", "4K UHD + HDR", "SD", ...)
  simultaneous_streams  : int (0 when unknown / N/A)
  minimum_term_months   : int (0 = no minimum / flexible monthly)
  active                : bool
  region                : "GB"
  source_url            : provider's official pricing page
  price_verified_at     : ISO date string of last verification
  is_promo              : bool (True → a promotional row, never a standard price)
  promo_ends            : optional ISO date string (only meaningful for promos)
  addon                 : bool (True → an add-on, e.g. NOW Boost; not standalone)
"""
from __future__ import annotations

from typing import List, Optional

# All UK pricing was verified against provider pricing pages on this date.
VERIFIED = "2026-08-03"
# Older verification date used for prices that could NOT be confidently
# re-verified from an official UK page during this pass.
VERIFIED_STALE = "2025-01-01"

REGION = "GB"
CURRENCY = "GBP"


def _plan(
    id: str,
    service_id: str,
    name: str,
    monthly_price: float,
    *,
    annual_price: Optional[float] = None,
    billing_type: str = "monthly",
    has_ads: bool = False,
    video_quality: str = "1080p",
    simultaneous_streams: int = 1,
    minimum_term_months: int = 0,
    active: bool = True,
    source_url: str = "",
    price_verified_at: str = VERIFIED,
    is_promo: bool = False,
    promo_ends: Optional[str] = None,
    addon: bool = False,
) -> dict:
    return {
        "id": id,
        "service_id": service_id,
        "name": name,
        "monthly_price": float(monthly_price),
        "annual_price": (float(annual_price) if annual_price is not None else None),
        "billing_type": billing_type,
        "has_ads": bool(has_ads),
        "video_quality": video_quality,
        "simultaneous_streams": int(simultaneous_streams),
        "minimum_term_months": int(minimum_term_months),
        "active": bool(active),
        "region": REGION,
        "source_url": source_url,
        "price_verified_at": price_verified_at,
        "is_promo": bool(is_promo),
        "promo_ends": promo_ends,
        "addon": bool(addon),
        # Marks the row as coming from this seed table. Admin writes flip this
        # to False (and set admin_modified) so future seeds never overwrite them.
        "seed_managed": True,
    }


# ── Canonical UK plan table ────────────────────────────────────────────────
UK_PLANS: List[dict] = [
    # ── Netflix ─────────────────────────────────────────────────────────────
    _plan("netflix_ads", "netflix", "Standard with Ads", 5.99,
          has_ads=True, video_quality="1080p", simultaneous_streams=2,
          source_url="https://help.netflix.com/en/node/24926"),
    _plan("netflix_standard", "netflix", "Standard", 12.99,
          video_quality="1080p", simultaneous_streams=2,
          source_url="https://help.netflix.com/en/node/24926"),
    _plan("netflix_premium", "netflix", "Premium", 18.99,
          video_quality="4K UHD + HDR", simultaneous_streams=4,
          source_url="https://help.netflix.com/en/node/24926"),

    # ── Amazon Prime / Prime Video ────────────────────────────────────────────
    _plan("amazon_prime", "prime_video", "Amazon Prime", 8.99,
          annual_price=95.0, billing_type="monthly",
          video_quality="4K UHD", simultaneous_streams=3,
          source_url="https://www.amazon.co.uk/amazonprime"),
    _plan("prime_video_only", "prime_video", "Prime Video only", 8.99,
          video_quality="4K UHD", simultaneous_streams=3,
          source_url="https://www.amazon.co.uk/amazonprime"),

    # ── Disney+ ─────────────────────────────────────────────────────────────
    _plan("disney_ads", "disney_plus", "Standard with Ads", 5.99,
          has_ads=True, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.disneyplus.com/en-gb/welcome/plans-pricing"),
    _plan("disney_standard", "disney_plus", "Standard", 9.99,
          annual_price=99.90, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.disneyplus.com/en-gb/welcome/plans-pricing"),
    _plan("disney_premium", "disney_plus", "Premium", 14.99,
          annual_price=149.90, video_quality="4K UHD + HDR", simultaneous_streams=4,
          source_url="https://www.disneyplus.com/en-gb/welcome/plans-pricing"),

    # ── Apple TV+ ───────────────────────────────────────────────────────────
    _plan("apple_tv_plus", "apple_tv", "Apple TV+", 9.99,
          annual_price=99.0, video_quality="4K UHD + HDR", simultaneous_streams=6,
          source_url="https://tv.apple.com/"),

    # ── Paramount+ ──────────────────────────────────────────────────────────
    _plan("paramount_ads", "paramount", "Basic with Ads", 4.99,
          has_ads=True, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.paramountplus.com/intl/"),
    _plan("paramount_premium", "paramount", "Premium", 10.99,
          annual_price=109.90, video_quality="4K UHD", simultaneous_streams=4,
          source_url="https://www.paramountplus.com/intl/"),

    # ── ITVX ────────────────────────────────────────────────────────────────
    _plan("itvx_free", "itvx", "ITVX Free", 0.0,
          billing_type="free", has_ads=True, video_quality="1080p",
          simultaneous_streams=2,
          source_url="https://www.itv.com/watch/itvx-premium"),
    _plan("itvx_premium", "itvx", "ITVX Premium", 5.99,
          annual_price=59.99, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.itv.com/watch/itvx-premium"),

    # ── NOW (now_tv) ──────────────────────────────────────────────────────────
    _plan("now_entertainment", "now_tv", "Entertainment", 7.99,
          video_quality="720p", simultaneous_streams=1, minimum_term_months=0,
          source_url="https://www.nowtv.com/gb/passes"),
    _plan("now_cinema", "now_tv", "Cinema", 9.99,
          video_quality="720p", simultaneous_streams=1,
          source_url="https://www.nowtv.com/gb/passes"),
    _plan("now_sports_month", "now_tv", "Sports Month", 34.99,
          video_quality="720p", simultaneous_streams=1,
          source_url="https://www.nowtv.com/gb/passes"),
    _plan("now_sports_day", "now_tv", "Sports Day", 14.99,
          video_quality="720p", simultaneous_streams=1,
          source_url="https://www.nowtv.com/gb/passes"),
    _plan("now_boost", "now_tv", "Boost", 6.0,
          addon=True, video_quality="1080p", simultaneous_streams=3,
          source_url="https://www.nowtv.com/gb/passes"),
    _plan("now_ultra_boost", "now_tv", "Ultra Boost", 9.0,
          addon=True, video_quality="4K UHD", simultaneous_streams=4,
          source_url="https://www.nowtv.com/gb/passes"),

    # ── discovery+ ──────────────────────────────────────────────────────────
    _plan("discovery_entertainment", "discovery_plus", "Entertainment", 3.99,
          has_ads=True, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.discoveryplus.com/gb/"),
    _plan("discovery_tnt_sports", "discovery_plus", "TNT Sports", 30.99,
          video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.discoveryplus.com/gb/"),

    # ── Channel 4 ─────────────────────────────────────────────────────────────
    _plan("channel4_free", "channel_4", "Channel 4 Free", 0.0,
          billing_type="free", has_ads=True, video_quality="1080p",
          simultaneous_streams=2,
          source_url="https://www.channel4.com/faqs/general/channel-4"),
    _plan("channel4_plus", "channel_4", "Channel 4+", 3.99,
          has_ads=False, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.channel4.com/faqs/general/channel-4"),

    # ── BBC iPlayer (TV Licence required) ──────────────────────────────────────
    _plan("bbc_iplayer_licence", "bbc_iplayer", "BBC iPlayer", 0.0,
          billing_type="licence_required", has_ads=False,
          video_quality="1080p", simultaneous_streams=1,
          source_url="https://www.tvlicensing.co.uk/check-if-you-need-one"),

    # ── MUBI ────────────────────────────────────────────────────────────────
    _plan("mubi", "mubi", "MUBI", 11.99,
          annual_price=95.88, video_quality="4K UHD", simultaneous_streams=1,
          source_url="https://mubi.com/en/gb/plans"),
    _plan("mubi_go", "mubi", "MUBI GO", 19.99,
          video_quality="4K UHD", simultaneous_streams=1,
          source_url="https://mubi.com/en/gb/plans"),

    # ── Max (hbo_max) — best-known UK pricing could not be re-verified from an
    #    official UK Max page during this pass (Max GB launch pricing was still
    #    provisional), so this row carries the stale verification date. ──────────
    _plan("max_standard", "hbo_max", "Standard", 9.99,
          has_ads=False, video_quality="1080p", simultaneous_streams=2,
          source_url="https://www.max.com/", price_verified_at=VERIFIED_STALE),
    _plan("max_premium", "hbo_max", "Premium", 14.99,
          annual_price=149.90, video_quality="4K UHD + HDR", simultaneous_streams=4,
          source_url="https://www.max.com/", price_verified_at=VERIFIED_STALE),
]


# ── Derived accessors ──────────────────────────────────────────────────────

def plans_for_service(service_id: str, active_only: bool = True) -> List[dict]:
    out = [p for p in UK_PLANS if p["service_id"] == service_id]
    if active_only:
        out = [p for p in out if p.get("active")]
    return out


def cheapest_standard_price(service_id: str) -> float:
    """Cheapest STANDARD (non-promo, non-addon), PAID plan price for a service.

    Returns 0.0 for free / licence-required services or when the service has no
    paid standard plan. Used for backward-compat ``price_monthly`` on the
    service registry and as the savings fallback.
    """
    candidates = [
        p for p in UK_PLANS
        if p["service_id"] == service_id
        and p.get("active")
        and not p.get("is_promo")
        and not p.get("addon")
        and p.get("billing_type") not in ("free", "licence_required")
        and float(p.get("monthly_price") or 0) > 0
    ]
    if not candidates:
        return 0.0
    return min(float(p["monthly_price"]) for p in candidates)


def get_plan(plan_id: str) -> Optional[dict]:
    return next((p for p in UK_PLANS if p["id"] == plan_id), None)


# ── Mongo seeding ──────────────────────────────────────────────────────────
async def seed_pricing_plans(db) -> dict:
    """Idempotent, restart-safe upsert of UK_PLANS into ``streaming_plans``.

    Behaviour:
      * INSERT any plan whose id does not yet exist.
      * UPDATE existing plans ONLY when they are still ``seed_managed: True``
        and carry no ``admin_modified`` flag — this refreshes prices/metadata
        from the canonical table on restart while never clobbering admin edits.
      * NEVER delete rows (admin-added promos / custom plans persist).

    Returns a small summary dict for logging.
    """
    inserted = 0
    updated = 0
    skipped = 0
    for plan in UK_PLANS:
        existing = await db.streaming_plans.find_one({"id": plan["id"]})
        if existing is None:
            await db.streaming_plans.insert_one(dict(plan))
            inserted += 1
            continue
        # Preserve admin edits: only refresh seed-managed, unmodified docs.
        if existing.get("seed_managed") and not existing.get("admin_modified"):
            await db.streaming_plans.update_one(
                {"id": plan["id"]}, {"$set": dict(plan)}
            )
            updated += 1
        else:
            skipped += 1
    return {"inserted": inserted, "updated": updated, "skipped": skipped,
            "total": len(UK_PLANS)}
