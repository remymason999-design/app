#!/usr/bin/env python3
"""Re-fetch GB streaming providers for EVERY catalogue title.

Runnable:  cd backend && python scripts/refresh_gb_providers.py

Why: many movies_cache docs were enriched before the UK provider
normalization map existed (itvx / now_tv / channel_4 / discovery_plus /
bbc_iplayer / mubi), so their `providers_by_region.GB` only contains the old
services. This script re-fetches TMDB `/{kind}/{tmdb_id}/watch/providers` for
GB and rebuilds the region entry using the SAME extraction + normalization the
importer uses, so the result is identical to a fresh import.

Integrity rules (mirror catalog_import.enrich_providers_top):
  • Uses the exact same PROVIDER_MAP / normalize_provider / build_region_entry
    logic so counts match a real import.
  • Writes providers_by_region.GB AND (because GB == DEFAULT_REGION) the flat
    available_on/rent_on/buy_on mirrors + confidence flags — same as line ~681
    of catalog_import.py.
  • A failed / rate-limited fetch is SKIPPED and counted; it NEVER wipes an
    existing entry and is NEVER recorded as success or confirmed-empty.
  • No '$ne' version selectors, no bare `except: pass` masking bugs — every
    caught exception is logged with the movie id.
  • Rate limited to ≤ ~40 req/s with retry/backoff on HTTP 429.
"""
from __future__ import annotations

import os
import sys
import time
import asyncio
import logging

# Ensure the backend package root is importable when run as `python scripts/...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from pymongo import UpdateOne  # noqa: E402

from core import db  # noqa: E402
# Reuse the EXACT importer logic so results match a fresh import.
from catalog_import import TMDB_BASE, PROVIDER_MAP, _headers  # noqa: E402
from providers_util import (  # noqa: E402
    normalize_provider, build_region_entry, DEFAULT_REGION, KNOWN_SERVICE_IDS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh_gb_providers")

REGION = "GB"
# Same bucket mapping the importer uses (ads/free count as flatrate).
_BUCKET_MAP = {
    "flatrate": "flatrate", "ads": "flatrate", "free": "flatrate",
    "rent": "rent", "buy": "buy",
}

# ── Rate limiting: token bucket capped at ~40 req/s ────────────────────────
_MAX_RPS = 40
_CONCURRENCY = 20
_MAX_RETRIES = 5


class RateLimiter:
    """Simple async rate limiter: at most `rate` acquisitions per second."""

    def __init__(self, rate: int):
        self._min_interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = max(now, self._next_at) + self._min_interval


def _extract_gb(data: dict) -> dict[str, list]:
    """Extract normalized flatrate/rent/buy provider ids for GB.

    Mirrors catalog_import.enrich_providers_top._get_providers exactly:
      • PROVIDER_MAP by provider_id first.
      • else normalize_provider(provider_name); flatrate keeps only KNOWN
        subscription services, rent/buy keep the normalized name verbatim.
    """
    region_data = (data.get("results") or {}).get(REGION) or {}
    out: dict[str, set] = {"flatrate": set(), "rent": set(), "buy": set()}
    for src, dst in _BUCKET_MAP.items():
        for entry in (region_data.get(src) or []):
            mapped = PROVIDER_MAP.get(entry.get("provider_id"))
            if mapped:
                out[dst].add(mapped)
            elif entry.get("provider_name"):
                norm = normalize_provider(entry["provider_name"])
                if dst == "flatrate":
                    if norm in KNOWN_SERVICE_IDS:
                        out[dst].add(norm)
                else:
                    out[dst].add(norm)
    return {k: sorted(v) for k, v in out.items()}


async def _fetch_one(
    client: httpx.AsyncClient, limiter: RateLimiter, item: dict
) -> tuple[str, dict | None]:
    """Fetch GB providers for one title. Returns (movie_id, providers|None).

    `None` providers => fetch failed/skipped (never wipe existing data).
    Retries on 429 with exponential backoff.
    """
    kind = item.get("type", "movie")
    tmdb_id = item.get("tmdb_id")
    movie_id = item["id"]
    if not tmdb_id:
        return movie_id, None

    url = f"{TMDB_BASE}/{kind}/{tmdb_id}/watch/providers"
    for attempt in range(_MAX_RETRIES):
        await limiter.acquire()
        try:
            r = await client.get(url, headers=_headers(), timeout=15.0)
        except Exception as exc:
            logger.warning(f"Provider fetch {movie_id} (id={tmdb_id}) transport error: {exc}")
            # transient network — brief backoff then retry
            await asyncio.sleep(0.5 * (2 ** attempt))
            continue

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            delay = float(retry_after) if (retry_after and retry_after.isdigit()) else (0.5 * (2 ** attempt))
            logger.info(f"429 for {movie_id}; backing off {delay:.1f}s (attempt {attempt + 1})")
            await asyncio.sleep(delay)
            continue

        try:
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning(f"Provider fetch {movie_id} (id={tmdb_id}) HTTP error: {exc}")
            return movie_id, None

        return movie_id, _extract_gb(data)

    logger.warning(f"Provider fetch {movie_id} (id={tmdb_id}) gave up after {_MAX_RETRIES} retries")
    return movie_id, None


async def main() -> None:
    # Plain find, projecting ONLY the fields we need. No aggregation.
    items = await db.movies_cache.find(
        {}, {"_id": 0, "id": 1, "tmdb_id": 1, "type": 1}
    ).to_list(length=None)
    total = len(items)
    logger.info(f"Refreshing GB providers for {total} titles (region={REGION}, DEFAULT_REGION={DEFAULT_REGION})")

    limiter = RateLimiter(_MAX_RPS)
    sem = asyncio.Semaphore(_CONCURRENCY)
    limits = httpx.Limits(max_connections=_CONCURRENCY + 5, max_keepalive_connections=_CONCURRENCY)

    enriched = 0
    skipped = 0
    processed = 0
    ops: list[UpdateOne] = []
    write_lock = asyncio.Lock()

    async def _flush(force: bool = False) -> None:
        nonlocal ops
        if not ops:
            return
        if not force and len(ops) < 500:
            return
        async with write_lock:
            batch, ops = ops, []
        for i in range(0, len(batch), 500):
            try:
                await db.movies_cache.bulk_write(batch[i:i + 500], ordered=False)
            except Exception as exc:
                logger.warning(f"Provider write batch failed: {exc}")

    async def _worker(item: dict) -> None:
        nonlocal enriched, skipped, processed
        async with sem:
            movie_id, providers = await _fetch_one(client, limiter, item)
        if providers is None:
            skipped += 1
        else:
            entry = build_region_entry(
                providers.get("flatrate", []),
                providers.get("rent", []),
                providers.get("buy", []),
            )
            set_fields: dict = {f"providers_by_region.{REGION}": entry}
            # GB == DEFAULT_REGION here → keep the flat mirrors in sync exactly
            # like catalog_import.py ~line 681.
            if REGION == DEFAULT_REGION:
                set_fields.update({
                    "available_on":              entry["available_on"],
                    "rent_on":                   entry["rent_on"],
                    "buy_on":                    entry["buy_on"],
                    "providers_fetched":         True,
                    "providers_fetched_at":      entry["fetched_at"],
                    "providers_region":          REGION,
                    "providers_empty_confirmed": entry["empty_confirmed"],
                    "provider_confidence":       entry["confidence"],
                })
            async with write_lock:
                ops.append(UpdateOne({"id": movie_id}, {"$set": set_fields}))
            enriched += 1

        processed += 1
        if processed % 500 == 0:
            logger.info(f"Progress: {processed}/{total} (enriched={enriched}, skipped={skipped})")
            await _flush()

    async with httpx.AsyncClient(timeout=15.0, limits=limits) as client:
        # Chunk task creation so we don't build 6k coroutines at once.
        chunk = 200
        for start in range(0, total, chunk):
            await asyncio.gather(*[_worker(it) for it in items[start:start + chunk]])
            await _flush()

    await _flush(force=True)
    logger.info(f"Done: {processed}/{total} processed — enriched={enriched}, skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
