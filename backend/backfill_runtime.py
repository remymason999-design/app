"""One-off maintenance: backfill movie `runtime` from TMDB.

Many movies were imported without a per-title detail fetch, leaving
`runtime=None`. The Discover quality gate gives None-runtime films the benefit
of the doubt (so they are still recommended), but the cards cannot display a
film length. This script fetches each missing movie's runtime from the TMDB
detail endpoint and persists it to `movies_cache`.

Run from backend/:  python3 backfill_runtime.py
"""
import asyncio
import logging

import httpx
from pymongo import UpdateOne

import core
from tmdb import TMDB_BASE, _headers

logger = logging.getLogger("backfill_runtime")
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    await core.load_catalog_from_db()
    cat = core.get_catalog()
    missing = [
        m for m in cat
        if m.get("type") == "movie"
        and (m.get("runtime") is None or int(m.get("runtime") or 0) <= 0)
        and m.get("tmdb_id")
    ]
    logger.info(f"Movies needing runtime backfill: {len(missing)}")
    if not missing:
        return

    sem = asyncio.Semaphore(6)  # ~30 req/s, under TMDB's 40 req/s burst limit
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=6)

    async def fetch(client: httpx.AsyncClient, m: dict):
        tmdb_id = m["tmdb_id"]
        async with sem:
            try:
                r = await client.get(
                    f"{TMDB_BASE}/movie/{tmdb_id}",
                    headers=_headers(),
                    timeout=15.0,
                )
                r.raise_for_status()
                rt = int(r.json().get("runtime") or 0)
            except Exception as exc:
                logger.debug(f"runtime fetch {m['id']}: {exc}")
                return None
        if rt <= 0:
            return None  # genuinely unknown/placeholder — leave as-is
        return UpdateOne(
            {"id": m["id"]},
            {"$set": {"runtime": rt, "total_runtime": rt}},
        )

    async with httpx.AsyncClient(timeout=15.0, limits=limits) as client:
        results = await asyncio.gather(*[fetch(client, m) for m in missing])

    ops = [op for op in results if op is not None]
    logger.info(f"Fetched runtimes for {len(ops)}/{len(missing)} movies")
    written = 0
    for i in range(0, len(ops), 500):
        try:
            res = await core.db.movies_cache.bulk_write(ops[i:i + 500], ordered=False)
            written += res.modified_count
        except Exception as exc:
            logger.warning(f"runtime backfill write: {exc}")
    logger.info(f"Backfill complete: {written} movies updated with runtime")


if __name__ == "__main__":
    asyncio.run(main())
