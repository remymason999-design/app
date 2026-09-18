"""Provider accuracy helpers: alias normalization + region-aware resolution.

Two trust problems are solved here:

1. Aliases — TMDB (and our import passes) surface the same service under many
   different names: "HBO Max", "HBO", "HBO Go", "Max"; "Amazon Video",
   "Prime Video"; "Apple TV", "Apple TV+".  Showing the same service three
   different ways erodes trust, so every provider name is mapped to ONE
   canonical service id before storage and before display.

2. Region — streaming availability is region-specific.  A title on Netflix GB
   may be rent-only (or absent) in the US.  Provider data is therefore stored
   keyed by region (`providers_by_region.{GB,US,CA,AU,…}`) and resolved against
   the *user's* region at serve time.  Legacy flat fields (`available_on` etc.)
   are kept as the DEFAULT_REGION projection for backwards compatibility.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

# Server default region — the region the bulk enrichment pass + in-memory
# engine operate on.  Flat provider fields always mirror this region.
DEFAULT_REGION = (os.environ.get("TMDB_REGION", "GB") or "GB").upper()

# Regions we actively store/serve provider data for.
SUPPORTED_REGIONS = ("GB", "US", "CA", "AU", "IE", "DE", "FR", "IN")

# Provider data older than this is considered stale and eligible for refresh.
PROVIDER_STALE_DAYS = 30

# ── Canonical alias map ───────────────────────────────────────────────────────
# Maps any lowercased provider name/variant (from TMDB or our internal ids) to a
# single canonical service id.  Applied at import time AND at query time so old
# records normalize on read even if they were stored before this map existed.
PROVIDER_ALIAS_MAP: dict[str, str] = {
    # Max / HBO family → "hbo_max" (display name "Max")
    "max":                      "hbo_max",
    "hbo max":                  "hbo_max",
    "hbo":                      "hbo_max",
    "hbo go":                   "hbo_max",
    "hbo now":                  "hbo_max",
    "hbo max amazon channel":   "hbo_max",
    "hbo_max":                  "hbo_max",
    # Prime Video / Amazon → "prime_video"
    "prime video":             "prime_video",
    "amazon prime video":      "prime_video",
    "amazon prime video with ads": "prime_video",
    "amazon video":            "prime_video",
    "amazon instant video":    "prime_video",
    "prime_video":             "prime_video",
    "amazon_video":            "prime_video",
    # Apple → "apple_tv" (display "Apple TV+")
    "apple tv":                "apple_tv",
    "apple tv+":               "apple_tv",
    "apple tv plus":           "apple_tv",
    "apple itunes":            "apple_tv",
    "itunes":                  "apple_tv",
    "apple_tv":                "apple_tv",
    # Disney → "disney_plus" (display "Disney+")
    "disney plus":             "disney_plus",
    "disney+":                 "disney_plus",
    "disney_plus":             "disney_plus",
    # Paramount → "paramount" (display "Paramount+")
    "paramount plus":          "paramount",
    "paramount+":              "paramount",
    "paramount+ amazon channel": "paramount",
    "paramount":               "paramount",
    # Netflix
    "netflix":                 "netflix",
    "netflix basic with ads":  "netflix",
    "netflix standard with ads": "netflix",
    # Hulu
    "hulu":                    "hulu",
    # Peacock
    "peacock":                 "peacock",
    "peacock premium":         "peacock",
    "peacock premium plus":    "peacock",
    # ITVX (ITV)
    "itvx":                    "itvx",
    "itv":                     "itvx",
    "itv hub":                 "itvx",
    "itvx premium":            "itvx",
    # NOW (Sky NOW / Now TV)
    "now tv":                  "now_tv",
    "now":                     "now_tv",
    "now_tv":                  "now_tv",
    # Channel 4 / All 4
    "channel 4":               "channel_4",
    "all 4":                   "channel_4",
    "channel4":                "channel_4",
    "channel_4":               "channel_4",
    # discovery+
    "discovery+":              "discovery_plus",
    "discovery plus":          "discovery_plus",
    "discovery_plus":          "discovery_plus",
    # BBC iPlayer
    "bbc iplayer":             "bbc_iplayer",
    "bbc_iplayer":             "bbc_iplayer",
    # MUBI
    "mubi":                    "mubi",
}

# Canonical ids that correspond to a subscription service we know about.
# (Used only for typing/clarity — normalization works for any input.)
KNOWN_SERVICE_IDS = {
    "netflix", "disney_plus", "hbo_max", "prime_video",
    "apple_tv", "hulu", "paramount", "peacock",
    "itvx", "now_tv", "channel_4", "discovery_plus", "bbc_iplayer", "mubi",
}


def normalize_provider(name: Optional[str]) -> Optional[str]:
    """Normalize one provider name/id to its canonical service id.

    Returns the canonical id when the input is a recognized service, otherwise
    returns the original input (trimmed) so genuinely-unknown rent/buy
    storefronts — "Google Play Movies", "Sky Store", "Rakuten TV" — are kept
    verbatim instead of being silently dropped.
    """
    if not name:
        return None
    raw = str(name).strip()
    if not raw:
        return None
    return PROVIDER_ALIAS_MAP.get(raw.lower(), raw)


def normalize_provider_list(names: Optional[Iterable[str]]) -> list[str]:
    """Normalize + de-duplicate a list of provider names, order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for n in names or []:
        c = normalize_provider(n)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _is_stale(fetched_at: Optional[str]) -> bool:
    """True if an ISO timestamp is older than PROVIDER_STALE_DAYS (or missing)."""
    if not fetched_at:
        return True
    try:
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return (datetime.now(timezone.utc) - ts) > timedelta(days=PROVIDER_STALE_DAYS)


def compute_confidence(
    flatrate: list[str],
    rent: list[str],
    buy: list[str],
    fetched_at: Optional[str],
    empty_confirmed: bool,
) -> str:
    """Stored, data-quality confidence for a region entry.

    This is independent of the user's subscriptions (that relative confidence is
    computed in the engine).  It answers: "how much do we trust this availability
    record itself?"

      high   — has subscription/flatrate availability, freshly fetched
      medium — rent/buy only, OR flatrate but stale
      low    — confirmed empty, or stale with no flatrate
      none   — never fetched / unknown
    """
    stale = _is_stale(fetched_at)
    if flatrate:
        return "medium" if stale else "high"
    if rent or buy:
        return "low" if stale else "medium"
    if empty_confirmed:
        return "low"
    return "none"


def build_region_entry(
    flatrate: Iterable[str],
    rent: Iterable[str],
    buy: Iterable[str],
    *,
    fetched_at: Optional[str] = None,
) -> dict:
    """Assemble a normalized, self-describing per-region provider entry."""
    fa = fetched_at or datetime.now(timezone.utc).isoformat()
    fl = normalize_provider_list(flatrate)
    rn = normalize_provider_list(rent)
    by = normalize_provider_list(buy)
    empty_confirmed = not fl and not rn and not by
    return {
        "available_on":    fl,
        "rent_on":         rn,
        "buy_on":          by,
        "fetched_at":      fa,
        "empty_confirmed": empty_confirmed,
        "confidence":      compute_confidence(fl, rn, by, fa, empty_confirmed),
    }


def resolve_region_providers(movie: dict, region: Optional[str]) -> dict:
    """Resolve a title's provider availability for a specific region.

    Resolution order:
      1. `providers_by_region[region]` — the canonical region-keyed store.
      2. Legacy flat fields, but ONLY when they actually represent `region`
         (i.e. region == DEFAULT_REGION, or the stored `providers_region`
         matches).  This keeps pre-migration GB records valid for GB users.
      3. Otherwise a not-matched empty result, signalling the caller to offer
         an on-demand refresh for the user's region.

    Always returns a dict with:
      available_on, rent_on, buy_on (normalized lists),
      fetched_at, empty_confirmed, confidence, region, region_matched, stale
    """
    region = (region or DEFAULT_REGION).upper()
    by_region = movie.get("providers_by_region") or {}

    entry = by_region.get(region)
    if isinstance(entry, dict):
        fa = entry.get("fetched_at")
        return {
            "available_on":    normalize_provider_list(entry.get("available_on")),
            "rent_on":         normalize_provider_list(entry.get("rent_on")),
            "buy_on":          normalize_provider_list(entry.get("buy_on")),
            "fetched_at":      fa,
            "empty_confirmed": bool(entry.get("empty_confirmed")),
            "confidence":      entry.get("confidence")
                               or compute_confidence(
                                   entry.get("available_on") or [],
                                   entry.get("rent_on") or [],
                                   entry.get("buy_on") or [],
                                   fa,
                                   bool(entry.get("empty_confirmed")),
                               ),
            "region":          region,
            "region_matched":  True,
            "stale":           _is_stale(fa),
        }

    # Legacy flat-field fallback — valid only when those fields represent `region`.
    legacy_region = (movie.get("providers_region") or DEFAULT_REGION).upper()
    flat_represents_region = (
        movie.get("providers_fetched") is True and legacy_region == region
    )
    if flat_represents_region:
        fa = movie.get("providers_fetched_at")
        fl = normalize_provider_list(movie.get("available_on"))
        rn = normalize_provider_list(movie.get("rent_on"))
        by = normalize_provider_list(movie.get("buy_on"))
        ec = bool(movie.get("providers_empty_confirmed")) or (not fl and not rn and not by)
        return {
            "available_on":    fl,
            "rent_on":         rn,
            "buy_on":          by,
            "fetched_at":      fa,
            "empty_confirmed": ec,
            "confidence":      compute_confidence(fl, rn, by, fa, ec),
            "region":          region,
            "region_matched":  True,
            "stale":           _is_stale(fa),
        }

    # No trustworthy data for this region.
    return {
        "available_on":    [],
        "rent_on":         [],
        "buy_on":          [],
        "fetched_at":      None,
        "empty_confirmed": False,
        "confidence":      "none",
        "region":          region,
        "region_matched":  False,
        "stale":           True,
    }


def needs_region_refresh(movie: dict, region: Optional[str]) -> bool:
    """True if we lack fresh, trustworthy provider data for `region`."""
    resolved = resolve_region_providers(movie, region)
    if not resolved["region_matched"]:
        return True
    if resolved["stale"]:
        return True
    # Region matched but produced no data and was never confirmed-empty →
    # likely a poisoned / partial record; refresh.
    has_any = resolved["available_on"] or resolved["rent_on"] or resolved["buy_on"]
    if not has_any and not resolved["empty_confirmed"]:
        return True
    return False
