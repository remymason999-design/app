"""Server-owned contracts for future monetisation.

This module deliberately contains no payment, advertising, affiliate activation,
or entitlement-granting code.  It is the single place where future account
tiers, access identifiers, and launch flags are defined so present-day feature
routes do not grow scattered subscription checks.
"""
from datetime import datetime
from typing import Optional


MONETIZATION_FLAGS = {
    "plus_visible": True,
    "plus_interest_enabled": True,
    "subscriptions_enabled": False,
    "ads_enabled": False,
    "affiliate_tracking_enabled": False,
    "sponsored_content_enabled": False,
}

ACCOUNT_TIERS = ("free", "plus", "duo", "family")
ACCOUNT_STATUSES = ("none", "trial", "active", "expired", "cancelled")
PLUS_ENTITLEMENTS = (
    "advanced_recommendations",
    "advanced_taste_insights",
    "advanced_savings",
    "advanced_friend_matching",
    "smart_alerts",
    "ad_free",
    "family_profiles",
)

# These are extension points only.  They are intentionally not products,
# prices, transactions, or feature gates.
FUTURE_REVENUE_STREAMS = (
    "plus_monthly_yearly",
    "duo",
    "family",
    "advertising",
    "affiliate_referrals",
    "savings_referrals",
    "sponsored_collections",
    "partnerships",
)

PLUS_EVENT_NAMES = (
    "plus_card_viewed",
    "plus_card_clicked",
    "plus_preview_viewed",
    "plus_interest_clicked",
    "plus_interest_removed",
)
PLUS_EVENT_SOURCES = {"profile", "profile_card", "plus_preview", "unknown"}
PLUS_EVENT_PLATFORMS = {"web", "ios", "android", "unknown"}


def _iso_or_none(value) -> Optional[str]:
    """Return only date-like legacy values; never expose arbitrary objects."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()[:64]
    return None


def resolve_account_entitlements(user: dict) -> dict:
    """Resolve a public, read-time account snapshot with safe legacy defaults.

    User documents are never modified here.  In particular, launch interest
    does not alter tier/status and no client-provided value can reach this
    function through a write endpoint.
    """
    raw_tier = user.get("subscription_tier")
    tier = raw_tier if raw_tier in ACCOUNT_TIERS else "free"
    raw_status = user.get("subscription_status")
    status = raw_status if raw_status in ACCOUNT_STATUSES else "none"
    if tier == "free" and status != "none":
        # A legacy status without a paid tier is not a valid active membership.
        status = "none"

    # No paid products are live.  Keep the access shape ready for future
    # activation but grant nothing today, including to a launch-interest user.
    feature_access = {name: False for name in PLUS_ENTITLEMENTS}
    return {
        "subscription_tier": tier,
        "subscription_status": status,
        "subscription_started_at": _iso_or_none(user.get("subscription_started_at")),
        "subscription_expires_at": _iso_or_none(user.get("subscription_expires_at")),
        "subscription_platform": (
            user.get("subscription_platform")
            if isinstance(user.get("subscription_platform"), str)
            else None
        ),
        "subscription_product_id": (
            user.get("subscription_product_id")
            if isinstance(user.get("subscription_product_id"), str)
            else None
        ),
        "entitlements": [],
        "feature_access": feature_access,
    }


def sanitized_public_config() -> dict:
    """Return only values safe for an unauthenticated client to consume."""
    return {
        "flags": dict(MONETIZATION_FLAGS),
        "entitlements": list(PLUS_ENTITLEMENTS),
        "future_revenue_streams": list(FUTURE_REVENUE_STREAMS),
        "sponsorship": {
            "is_sponsored": False,
            "sponsor_name": None,
            "campaign_id": None,
            "sponsored_label": "Sponsored",
        },
    }


def sponsorship_metadata(content: Optional[dict]) -> dict:
    """Normalize optional future sponsorship metadata without scoring fields."""
    content = content or {}
    sponsored = bool(content.get("is_sponsored", False))
    return {
        "is_sponsored": sponsored,
        "sponsor_name": (
            str(content["sponsor_name"]).strip()[:120]
            if sponsored and content.get("sponsor_name")
            else None
        ),
        "campaign_id": (
            str(content["campaign_id"]).strip()[:120]
            if sponsored and content.get("campaign_id")
            else None
        ),
        "sponsored_label": "Sponsored" if sponsored else None,
    }