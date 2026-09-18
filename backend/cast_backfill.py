"""Backfill cast / director / studio metadata for movies_cache documents.

Movies and TV imported before this feature lack cast_names, director_names, and
studio_names. This module fetches those fields from TMDB in bounded-concurrency
batches and updates the cache in place. Resumable across restarts: only docs
WITHOUT cast_names are processed, so re-running is cheap.
"""
import asyncio
import os
from typing import Optional

import httpx

from core import db, logger

# Bump whenever _fetch_extras starts persisting a new field so previously
# backfilled docs get re-processed once and then stop matching the selector.
#   v2 — recommendation metadata (themes, franchises, trailers, …)
#   v3 — adds search fields (aliases, collections)
#   v4 — adds writer_names
#   v5 — persists the stable TMDB collection id as well as its display name
_METADATA_VERSION = 5

# Version for search-index enrichment (used by content.py search rebuild).
# Bumping this triggers a re-index without re-fetching TMDB data.
SEARCH_ENRICH_VERSION = 1

_API = "https://api.themoviedb.org/3"
_TOKEN = os.environ.get("TMDB_BEARER_TOKEN") or ""
_HEADERS = {"Authorization": f"Bearer {_TOKEN}", "accept": "application/json"} if _TOKEN else {}


async def _fetch_extras(client: httpx.AsyncClient, kind: str, tmdb_id: int) -> Optional[dict]:
    """Fetch credits + production_companies for one TMDB item.

    Returns:
      dict      — extracted fields (may have empty arrays if TMDB simply has no data)
      None      — TRANSIENT failure (timeout / 429 / 5xx / network); caller should
                  NOT persist anything so the doc remains eligible for retry.
    """
    # One detail call with every relevant section appended:
    #   credits / aggregate_credits → cast + director
    #   keywords                    → theme keywords
    #   videos                      → trailers (recommendation feed)
    #   alternative_titles          → search aliases (regional / translated names)
    appended = (
        "credits,keywords,videos,alternative_titles"
        if kind == "movie"
        else "credits,aggregate_credits,keywords,videos,alternative_titles"
    )
    try:
        r = await client.get(
            f"{_API}/{kind}/{tmdb_id}",
            params={"append_to_response": appended},
            headers=_HEADERS,
            timeout=10.0,
        )
    except Exception:
        return None  # transient — don't poison the doc
    # 429 + 5xx are transient; 404 is a hard miss (record empty so we stop trying).
    if r.status_code == 404:
        # Hard miss — record terminal sentinel so the selector stops re-queuing.
        return {
            "cast_names": [], "director_names": [], "writer_names": [], "studio_names": [],
            "status": "Unknown", "production_countries": [],
            "spoken_languages": [], "collection_id": None, "collection_name": None,
            "franchises": [], "themes": [], "keywords": [],
            "trailer_youtube_id": None,
            "aliases": [], "collections": [],
            "metadata_version": _METADATA_VERSION,
        }
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception:
        return None

    credits_root = (
        d.get("aggregate_credits")
        if kind == "tv" and d.get("aggregate_credits")
        else (d.get("credits") or {})
    )
    cast_names = [c.get("name") for c in (credits_root.get("cast") or []) if c.get("name")][:15]
    director_names: list[str] = []
    writer_names: list[str] = []
    DIRECTOR_JOBS = {"Director", "Series Director"}
    WRITER_JOBS = {"Writer", "Screenwriter", "Story", "Novel", "Author"}
    for c in (credits_root.get("crew") or []):
        # /credits has top-level `job`; aggregate_credits has `jobs[]`.
        job_titles: set = set()
        if c.get("job"):
            job_titles.add(c["job"])
        for j in (c.get("jobs") or []):
            jn = (j or {}).get("job")
            if jn:
                job_titles.add(jn)
        if job_titles & DIRECTOR_JOBS:
            n = c.get("name")
            if n and n not in director_names:
                director_names.append(n)
        if job_titles & WRITER_JOBS:
            n = c.get("name")
            if n and n not in writer_names:
                writer_names.append(n)
    if kind == "tv":
        for creator in (d.get("created_by") or []):
            n = creator.get("name")
            if n and n not in director_names:
                director_names.append(n)
    studio_names = [c.get("name") for c in (d.get("production_companies") or []) if c.get("name")][:8]

    # ── Extended metadata (free — same TMDB call) ───────────────────────────
    production_countries = [
        c.get("iso_3166_1") for c in (d.get("production_countries") or [])
        if c.get("iso_3166_1")
    ]
    spoken_languages = [
        l.get("iso_639_1") for l in (d.get("spoken_languages") or [])
        if l.get("iso_639_1")
    ]
    status = d.get("status") or None
    collection = d.get("belongs_to_collection") if kind == "movie" else None
    collection_id = collection.get("id") if isinstance(collection, dict) else None
    collection_name = collection.get("name") if isinstance(collection, dict) else None
    kw_root = d.get("keywords") or {}
    raw_kw = kw_root.get("keywords") if kind == "movie" else kw_root.get("results")
    keywords = [k.get("name") for k in (raw_kw or []) if k.get("name")][:30]

    # Themes — semantic tags inferred from keywords + genres so consumers can
    # query without re-running content_cards on every load.
    THEME_KEYWORDS = {
        "true-crime":     {"true crime", "serial killer", "murder", "investigation"},
        "coming-of-age":  {"coming of age", "teenager", "high school"},
        "psychological":  {"psychological", "mind-bending", "psychological thriller"},
        "feel-good":      {"feel good", "heartwarming", "wholesome"},
        "dystopia":       {"dystopia", "post-apocalyptic", "dystopian future"},
        "underdog":       {"underdog", "rags to riches"},
        "redemption":     {"redemption", "second chance"},
        "survival":       {"survival", "stranded", "wilderness"},
        "heist":          {"heist", "robbery"},
        "war":            {"war", "wwii", "world war"},
        "courtroom":      {"courtroom", "legal drama", "trial"},
        "biopic":         {"biography", "biopic", "true story"},
        "musical":        {"musical", "broadway"},
    }
    kw_lower = {k.lower() for k in keywords}
    themes = sorted({
        theme for theme, hints in THEME_KEYWORDS.items()
        if kw_lower & hints
    })

    # Franchise = TMDB collection (movies). For TV, leave empty unless we
    # later derive franchise membership another way.
    franchises = [collection_name] if collection_name else []

    # Runtime / total_runtime + release_date for movies (TV uses seasons)
    extras_extra: dict = {
        "status":               status,
        "production_countries": production_countries,
        "spoken_languages":     spoken_languages,
        "collection_id":        collection_id,
        "collection_name":      collection_name,
        "franchises":           franchises,
        "themes":               themes,
    }
    # Always persist keywords (even empty) so the selector converges
    extras_extra["keywords"] = keywords

    # Trailer (YouTube key, official > teaser > first). Always set — None
    # is a terminal value when TMDB has no trailer for the title.
    videos = ((d.get("videos") or {}).get("results") or [])
    yt = [v for v in videos if (v.get("site") or "").lower() == "youtube" and v.get("key")]
    trailers   = [v for v in yt if (v.get("type") or "").lower() == "trailer"]
    teasers    = [v for v in yt if (v.get("type") or "").lower() == "teaser"]
    official_t = [v for v in trailers if v.get("official")]
    picked = (official_t or trailers or teasers or yt)
    extras_extra["trailer_youtube_id"] = picked[0]["key"] if picked else None
    if kind == "movie":
        rt = int(d.get("runtime") or 0)
        extras_extra["runtime"] = rt
        extras_extra["total_runtime"] = rt
        if d.get("release_date"):
            extras_extra["release_date"] = d["release_date"]
    else:
        # TV has no per-show runtime field. Persist sentinel so the
        # selector knows enrichment ran.
        extras_extra["runtime"] = None
        if d.get("first_air_date"):
            extras_extra["release_date"] = d["first_air_date"]

    # ── Aliases (alternative / regional / translated titles) ─────────────────
    alt_root = d.get("alternative_titles") or {}
    raw_alts = alt_root.get("titles") if kind == "movie" else alt_root.get("results")
    aliases: list[str] = []
    if isinstance(raw_alts, list):
        seen: set = set()
        for a in raw_alts:
            t = (a or {}).get("title")
            if t and t not in seen:
                seen.add(t)
                aliases.append(t)
        aliases = aliases[:20]
    # The original_title (or original_name for TV) is a search alias too.
    orig = d.get("original_title") if kind == "movie" else d.get("original_name")
    if orig and orig not in aliases:
        aliases.insert(0, orig)
        aliases = aliases[:20]

    # ── Collections / franchises (Harry Potter, Marvel Cinematic Universe…) ─
    collections: list[str] = []
    btc = d.get("belongs_to_collection")
    if isinstance(btc, dict) and btc.get("name"):
        collections.append(btc["name"])

    return {
        "cast_names": cast_names,
        "director_names": director_names[:5],
        "writer_names": writer_names[:5],
        "studio_names": studio_names,
        "metadata_version": _METADATA_VERSION,
        "aliases": aliases,
        "collections": collections,
        **extras_extra,
    }


async def backfill_credits(limit: int = 5000, concurrency: int = 16) -> int:
    """Fill missing cast / director / writer / studio metadata for movies_cache documents.

    Returns the number of documents updated. Idempotent and resumable —
    documents already carrying the current metadata_version are skipped.
    """
    if not _TOKEN:
        logger.info("Cast backfill skipped — TMDB_BEARER_TOKEN not set")
        return 0

    # Selector is version-based: any doc lacking the current metadata_version
    # is processed once, persisted with metadata_version=_METADATA_VERSION,
    # and stops matching on the next pass. Bumping _METADATA_VERSION (e.g. when
    # adding aliases / collections) re-enriches older docs automatically.
    # $or catches BOTH missing metadata_version (fresh imports) AND stale
    # metadata_version (previously-enriched docs from an older version).
    cursor = (
        db.movies_cache
        .find(
            {
                "tmdb_id": {"$exists": True},
                "$or": [
                    {"metadata_version": {"$exists": False}},
                    {"metadata_version": {"$ne": _METADATA_VERSION}},
                ],
            },
            {"_id": 0, "id": 1, "tmdb_id": 1, "type": 1, "title": 1},
        )
        .limit(limit)
    )
    todo = await cursor.to_list(length=limit)
    if not todo:
        return 0

    logger.info(f"Cast backfill: enriching {len(todo)} titles (concurrency={concurrency})")
    sem = asyncio.Semaphore(concurrency)
    updated = 0

    async with httpx.AsyncClient() as client:
        async def _one(doc: dict) -> None:
            nonlocal updated
            async with sem:
                kind = doc.get("type") or "movie"
                if kind not in ("movie", "tv"):
                    kind = "movie"
                extras = await _fetch_extras(client, kind, int(doc["tmdb_id"]))
                if extras is None:
                    # Transient failure (429/5xx/timeout) — leave doc untouched
                    # so it stays eligible for the next backfill pass.
                    return
                try:
                    payload = dict(extras)
                    payload["search_enrich_version"] = SEARCH_ENRICH_VERSION
                    await db.movies_cache.update_one(
                        {"id": doc["id"]},
                        {"$set": payload},
                    )
                    updated += 1
                except Exception:
                    pass

        await asyncio.gather(*[_one(d) for d in todo], return_exceptions=True)

    logger.info(f"Cast backfill: updated {updated}/{len(todo)} titles")
    return updated
