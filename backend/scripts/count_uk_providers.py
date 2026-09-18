#!/usr/bin/env python3
"""Count catalogue titles available per streaming provider in the UK (GB).

Runnable:  cd backend && python scripts/count_uk_providers.py

Connects to the SAME Mongo db the server uses (MONGO_URL + DB_NAME from the
environment) and prints, per canonical service id, how many titles list that
provider for the GB region. Two counts are reported for each provider:

  • flat `available_on`          — the legacy DEFAULT_REGION flat field
    (fast, indexed) which mirrors GB for this deployment.
  • providers_by_region.GB flatrate presence — the canonical region-keyed
    store's `available_on` array for GB.

Uses ONLY plain find/count_documents queries — no aggregation pipelines —
because the managed Mongo instance should avoid complex aggregations.
"""
import os
import sys
import asyncio

# Ensure the backend package root is importable when run as `python scripts/...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db  # noqa: E402
from providers_util import KNOWN_SERVICE_IDS  # noqa: E402

# Deterministic display order: UK-first, then global/US.
_ORDER = [
    "netflix", "disney_plus", "hbo_max", "prime_video", "apple_tv",
    "paramount", "itvx", "now_tv", "channel_4", "discovery_plus",
    "bbc_iplayer", "mubi", "hulu", "peacock",
]


async def main() -> None:
    service_ids = _ORDER + [s for s in sorted(KNOWN_SERVICE_IDS) if s not in _ORDER]

    total = await db.movies_cache.count_documents({})
    gb_enriched = await db.movies_cache.count_documents(
        {"providers_by_region.GB": {"$exists": True}}
    )

    rows = []
    for sid in service_ids:
        flat = await db.movies_cache.count_documents({"available_on": sid})
        gb = await db.movies_cache.count_documents(
            {"providers_by_region.GB.available_on": sid}
        )
        rows.append((sid, flat, gb))

    print(f"Total titles in movies_cache: {total}")
    print(f"Titles with providers_by_region.GB present: {gb_enriched}")
    print()
    print(f"{'provider_id':<16}{'flat available_on':>20}{'GB flatrate':>16}")
    print("-" * 52)
    for sid, flat, gb in rows:
        print(f"{sid:<16}{flat:>20}{gb:>16}")


if __name__ == "__main__":
    asyncio.run(main())
