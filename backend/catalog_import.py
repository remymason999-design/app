"""Large-scale TMDB catalog importer — genre-balanced, fully paginated.

Strategy
--------
Two tiers of endpoints are harvested in every import pass:

  GENERAL (~11 endpoints)
    Popular / trending / top-rated lists.  These surface whatever is hot right
    now but heavily bias toward high-popularity titles (blockbusters, big-budget
    TV).  Used with `pages_general` pages each.

  GENRE-SPECIFIC (~100 endpoints)
    One /discover/movie + /discover/tv call per genre, with three sort
    strategies each (vote_count, vote_average, popularity).  This guarantees
    that low-popularity genres (Documentary, Western, War, History, Music)
    get their own dedicated harvest slice and are never crowded out.
    Used with `pages_genre` pages each.

Typical yields at default settings (pages_general=10, pages_genre=5):
  ~560 HTTP requests  →  ~11 000 raw items  →  5 000–9 000 unique titles
  (all deduplicated by tmdb_id, highest-popularity copy wins)

Quality gates inside _light_enrich:
  - Must have poster, title, release date ≥ 1970, non-future
  - Must have a non-empty overview
  - vote_count ≥ 5 OR popularity ≥ 2 (keeps niche but real titles)

Provider data is written in a separate background pass (enrich_providers_top)
using $setOnInsert so previously-fetched provider data is never overwritten.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import httpx
from pymongo import UpdateOne

from providers_util import (
    normalize_provider, build_region_entry, DEFAULT_REGION, KNOWN_SERVICE_IDS,
)

logger = logging.getLogger("watchsmart.catalog_import")

TMDB_BASE = "https://api.themoviedb.org/3"
IMG_BASE  = "https://image.tmdb.org/t/p"

# ── TMDB genre-id → canonical app name ────────────────────────────────────────
GENRE_MAP: dict[int, str] = {
    # Movie genres
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "Drama",
    53: "Thriller", 10752: "War", 37: "Western",
    # TV-specific genre IDs
    10759: "Action",        # Action & Adventure
    10762: "Kids",
    10763: "Documentary",   # News (mapped to Documentary)
    10764: "Reality",
    10765: "Sci-Fi",        # Sci-Fi & Fantasy
    10766: "Drama",         # Soap
    10767: "Talk",
    10768: "War",           # War & Politics
}

# ── TMDB streaming provider id → our service id ───────────────────────────────
PROVIDER_MAP: dict[int, str] = {
    8:    "netflix",
    337:  "disney_plus",
    1899: "hbo_max",   # Max (US)
    384:  "hbo_max",   # legacy HBO Max (US)
    1825: "hbo_max",   # HBO Max Amazon Channel (GB / EU re-distributed Max)
    9:    "prime_video",
    119:  "prime_video",
    350:  "apple_tv",
    15:   "hulu",
    531:  "paramount",
    386:  "peacock",
    387:  "peacock",
}

# ── Genre sets ────────────────────────────────────────────────────────────────
# Genres with intrinsically low TMDB popularity scores need lower vote_count
# thresholds so their discover pages aren't completely empty.
_NICHE_GENRES = {"Documentary", "Western", "War", "History", "Music", "Animation"}

# Movie TMDB genre IDs (18 genres → all spec genres covered)
_MOVIE_GENRE_IDS: list[tuple[int, str]] = [
    (28,    "Action"),
    (12,    "Adventure"),
    (16,    "Animation"),
    (35,    "Comedy"),
    (80,    "Crime"),
    (99,    "Documentary"),
    (18,    "Drama"),
    (10751, "Family"),
    (14,    "Fantasy"),
    (36,    "History"),
    (27,    "Horror"),
    (10402, "Music"),
    (9648,  "Mystery"),
    (10749, "Romance"),
    (878,   "Sci-Fi"),
    (53,    "Thriller"),
    (10752, "War"),
    (37,    "Western"),
]

# TV TMDB genre IDs (uses TV-specific IDs where they differ from movie IDs)
_TV_GENRE_IDS: list[tuple[int, str]] = [
    (10759, "Action"),      # Action & Adventure
    (16,    "Animation"),
    (35,    "Comedy"),
    (80,    "Crime"),
    (99,    "Documentary"),
    (18,    "Drama"),
    (10751, "Family"),
    (14,    "Fantasy"),
    (27,    "Horror"),
    (10402, "Music"),
    (9648,  "Mystery"),
    (10749, "Romance"),
    (10765, "Sci-Fi"),      # Sci-Fi & Fantasy
    (53,    "Thriller"),
    (10768, "War"),         # War & Politics
    (37,    "Western"),
]


def _build_general_endpoints() -> list[tuple[str, str, dict]]:
    """Return the ~11 general popular/trending/top-rated endpoints."""
    return [
        # Movies
        ("movie", "/movie/popular",       {"region": "GB"}),
        ("movie", "/movie/top_rated",     {"region": "GB"}),
        ("movie", "/trending/movie/week", {}),
        ("movie", "/trending/movie/day",  {}),
        ("movie", "/discover/movie",      {"sort_by": "revenue.desc",    "vote_count.gte": 200}),
        ("movie", "/discover/movie",      {"sort_by": "vote_count.desc", "vote_count.gte": 100}),
        # TV
        ("tv", "/tv/popular",             {"region": "GB"}),
        ("tv", "/tv/top_rated",           {"region": "GB"}),
        ("tv", "/trending/tv/week",       {}),
        ("tv", "/trending/tv/day",        {}),
        ("tv", "/discover/tv",            {"sort_by": "vote_count.desc", "vote_count.gte": 50}),
    ]


def _build_genre_endpoints() -> list[tuple[str, str, dict]]:
    """Return one discover endpoint per genre/sort-strategy combination.

    Each genre gets three sort strategies for movies (vote_count, vote_average,
    popularity) and two for TV (vote_count, vote_average) so that both deep
    catalogs and critically-acclaimed niche titles are harvested.

    Niche genres use lower vote_count thresholds to avoid empty pages.
    """
    endpoints: list[tuple[str, str, dict]] = []

    # ── Movie genre endpoints ────────────────────────────────────────────────
    for genre_id, genre_name in _MOVIE_GENRE_IDS:
        gid = str(genre_id)
        is_niche = genre_name in _NICHE_GENRES

        # Sort 1: most-voted — surfaces well-known classics and crowd favourites
        endpoints.append(("movie", "/discover/movie", {
            "with_genres":    gid,
            "sort_by":        "vote_count.desc",
            "vote_count.gte": 20 if is_niche else 100,
        }))
        # Sort 2: highest-rated (with a minimum vote floor) — surfaces critically
        #         acclaimed titles that aren't necessarily mainstream-popular
        endpoints.append(("movie", "/discover/movie", {
            "with_genres":    gid,
            "sort_by":        "vote_average.desc",
            "vote_count.gte": 50 if is_niche else 200,
        }))
        # Sort 3: most popular right now — surfaces recent releases and trending
        endpoints.append(("movie", "/discover/movie", {
            "with_genres":    gid,
            "sort_by":        "popularity.desc",
            "vote_count.gte": 5 if is_niche else 30,
        }))

    # ── TV genre endpoints ───────────────────────────────────────────────────
    for genre_id, genre_name in _TV_GENRE_IDS:
        gid = str(genre_id)
        is_niche = genre_name in _NICHE_GENRES

        endpoints.append(("tv", "/discover/tv", {
            "with_genres":    gid,
            "sort_by":        "vote_count.desc",
            "vote_count.gte": 10 if is_niche else 50,
        }))
        endpoints.append(("tv", "/discover/tv", {
            "with_genres":    gid,
            "sort_by":        "vote_average.desc",
            "vote_count.gte": 20 if is_niche else 100,
        }))
        endpoints.append(("tv", "/discover/tv", {
            "with_genres":    gid,
            "sort_by":        "popularity.desc",
            "vote_count.gte": 5 if is_niche else 20,
        }))

    return endpoints


# ── Provider-first discover endpoints ────────────────────────────────────
# TMDB watch-provider IDs per region. Same provider can have different IDs
# region-to-region (Netflix is 8 in both GB and US; HBO Max is 1899 in US
# but 1825 in GB). Provider-first ingestion guarantees we surface titles
# that the genre/popular pages miss (deep back-catalogue per service).
_PROVIDER_IDS_BY_REGION: dict[str, list[tuple[int, str]]] = {
    "GB": [
        (8,    "netflix"),
        (337,  "disney_plus"),
        (1825, "hbo_max"),
        (9,    "prime_video"),
        (350,  "apple_tv"),
        (531,  "paramount"),
        # Transactional / rental marketplaces — caught at ingestion time so
        # the catalogue extends beyond pure-subscription services.
        (10,   "amazon_video"),   # Amazon rent/buy
        (192,  "youtube"),        # YouTube rent/buy
    ],
    "US": [
        (8,    "netflix"),
        (337,  "disney_plus"),
        (1899, "hbo_max"),
        (9,    "prime_video"),
        (350,  "apple_tv"),
        (15,   "hulu"),
        (531,  "paramount"),
        (386,  "peacock"),
        (10,   "amazon_video"),
        (192,  "youtube"),
    ],
}


def _build_provider_endpoints(regions: tuple[str, ...] = ("GB", "US")) -> list[tuple[str, str, dict]]:
    """One /discover/{movie,tv} endpoint per (provider × region × kind).

    Surfaces titles that popular/top-rated/trending pages bias against —
    in particular deep back-catalogue (Netflix originals, Disney+ kids, Max
    HBO classics) which would otherwise never appear in our index even
    though they are streamable in the user's region.
    """
    # Transactional services (rent/buy only) — narrow monetization filter
    # so we don't double-pull catalogue we already have from flatrate.
    _TRANSACTIONAL = {"amazon_video", "youtube"}
    endpoints: list[tuple[str, str, dict]] = []
    for region in regions:
        for prov_id, name in _PROVIDER_IDS_BY_REGION.get(region, []):
            for kind, path in (("movie", "/discover/movie"), ("tv", "/discover/tv")):
                params = {
                    "with_watch_providers": str(prov_id),
                    "watch_region":         region,
                    "sort_by":              "popularity.desc",
                    "vote_count.gte":       20,
                }
                if name in _TRANSACTIONAL:
                    params["with_watch_monetization_types"] = "rent|buy"
                endpoints.append((kind, path, params))

                # ── Mainstream-depth pass (Task #23 Step 2) ─────────────────
                # The popularity.desc pass above skims what's hot now; for the
                # subscription services we add a SECOND vote_count.desc flatrate
                # sweep to reach deep, well-known back-catalogue (the most-voted
                # titles a user already recognises) that trending pages bury.
                # Additive only: deduped by tmdb_id via $setOnInsert, never
                # overwrites existing rows, and applies solely to flatrate
                # (subscription) services so we don't re-pull rent/buy depth.
                if name not in _TRANSACTIONAL:
                    endpoints.append((kind, path, {
                        "with_watch_providers":          str(prov_id),
                        "watch_region":                  region,
                        "with_watch_monetization_types": "flatrate",
                        "sort_by":                       "vote_count.desc",
                        "vote_count.gte":                50,
                    }))
    return endpoints


# Pre-compute at module load so admin/debug tooling can inspect them
GENERAL_ENDPOINTS  = _build_general_endpoints()
GENRE_ENDPOINTS    = _build_genre_endpoints()
PROVIDER_ENDPOINTS = _build_provider_endpoints()

# Legacy alias so any code that imports ENDPOINTS still works
ENDPOINTS = GENERAL_ENDPOINTS + GENRE_ENDPOINTS + PROVIDER_ENDPOINTS


def _headers() -> dict:
    token = os.environ.get("TMDB_BEARER_TOKEN")
    if not token:
        raise RuntimeError("TMDB_BEARER_TOKEN missing")
    return {"Authorization": f"Bearer {token}", "accept": "application/json"}


def _light_enrich(item: dict, kind: str) -> Optional[dict]:
    """Convert one TMDB list-result into a catalog entry — zero extra API calls.

    Quality gates (returns None if any fail):
      • tmdb_id, title, release_date, poster_path must be present
      • release year ≥ 1970
      • non-empty overview (avoids placeholder/stub entries)
      • not a confirmed future release
      • vote_count ≥ 5 OR popularity ≥ 2
    """
    import datetime as _dt
    _today = _dt.date.today().isoformat()

    is_movie = kind == "movie"
    tmdb_id  = item.get("id")
    title    = item.get("title") if is_movie else item.get("name")
    date_str = (item.get("release_date") if is_movie else item.get("first_air_date")) or ""
    poster_path = item.get("poster_path")
    overview    = (item.get("overview") or "").strip()

    # Hard gates — missing critical fields
    if not tmdb_id or not title or not date_str or not poster_path:
        return None
    if not overview:
        return None

    try:
        year = int(date_str[:4])
    except (ValueError, TypeError):
        return None
    # Sanity floor only — classic / pre-1970 films are valid catalogue entries.
    # Discover ranking handles age-based downranking; search must remain wide.
    if year < 1900:
        return None

    # Reject confirmed future releases (no provider data, not watchable yet)
    if date_str > _today:
        return None

    vote_count = item.get("vote_count") or 0
    popularity = float(item.get("popularity") or 0)
    if vote_count < 5 and popularity < 2:
        return None

    # ── Genre mapping ────────────────────────────────────────────────────────
    genre_ids: list[int] = item.get("genre_ids") or []
    genres:    list[str] = []
    seen:      set[str]  = set()
    for gid in genre_ids:
        name = GENRE_MAP.get(gid)
        if name and name not in seen:
            genres.append(name)
            seen.add(name)

    # ── Tag inference ────────────────────────────────────────────────────────
    orig_lang = item.get("original_language") or ""
    tags: set[str] = set()
    if "Animation" in seen and orig_lang == "ja":
        tags.add("anime")
    if orig_lang in ("hi", "te", "ta", "kn", "ml"):
        tags.add("bollywood")
    if "Kids" in seen:
        tags.add("kids")
    if orig_lang and orig_lang != "en":
        tags.add(f"lang:{orig_lang}")

    return {
        "id":               f"tmdb_{kind}_{tmdb_id}",
        "tmdb_id":          tmdb_id,
        "title":            title,
        "year":             year,
        "release_date":     date_str,
        "rating":           round(float(item.get("vote_average") or 0), 1),
        "vote_count":       vote_count,
        "popularity":       popularity,
        "genres":           genres,
        "tags":             sorted(tags),
        "type":             "movie" if is_movie else "tv",
        "overview":         overview,
        "poster_url":       f"{IMG_BASE}/w780{poster_path}",
        "backdrop_url":     f"{IMG_BASE}/w1280{item['backdrop_path']}" if item.get("backdrop_path") else None,
        "trailer_youtube_id": None,
        "runtime":          None,
        "seasons":          None,
        "total_runtime":    None,
        "certification":    None,
        "keywords":         [],
        "original_language": orig_lang,
        # List endpoints normally omit this, but retain it when a TMDB payload
        # includes collection data so every ingestion path uses one schema.
        "collection_id": (
            (item.get("belongs_to_collection") or {}).get("id")
            if isinstance(item.get("belongs_to_collection"), dict) else None
        ),
        "collection_name": (
            (item.get("belongs_to_collection") or {}).get("name")
            if isinstance(item.get("belongs_to_collection"), dict) else None
        ),
        # Provider fields — populated by enrich_providers_top() later
        "available_on":    [],
        "rent_on":         [],
        "buy_on":          [],
        "providers_fetched": False,
    }


async def _fetch_page(
    client: httpx.AsyncClient,
    sem:    asyncio.Semaphore,
    kind:   str,
    path:   str,
    page:   int,
    extra:  dict,
) -> tuple[str, list]:
    """Fetch one TMDB list page and return (kind, results).

    Returns (kind, []) on any error so gather never raises.
    """
    async with sem:
        try:
            r = await client.get(
                f"{TMDB_BASE}{path}",
                params={"page": page, **extra},
                headers=_headers(),
                timeout=20.0,
            )
            r.raise_for_status()
            return kind, (r.json().get("results") or [])
        except Exception as exc:
            logger.debug(f"TMDB {path} p{page}: {type(exc).__name__}: {exc}")
            return kind, []


_CATALOG_BASE_FIELDS = {
    "title", "year", "release_date", "rating", "vote_count", "popularity",
    "genres", "tags", "type", "overview", "poster_url", "backdrop_url",
    "original_language", "tmdb_id", "collection_id", "collection_name",
}


def _catalog_update_document(movie: dict) -> dict:
    """Build a conflict-free Mongo update while preserving enriched metadata."""
    set_fields = {
        key: value for key, value in movie.items()
        if key in _CATALOG_BASE_FIELDS
        and (
            key not in {"collection_id", "collection_name"}
            or value is not None
        )
    }
    return {
        "$set": set_fields,
        "$setOnInsert": {
            "id":                   movie["id"],
            "trailer_youtube_id":   None,
            "runtime":              None,
            "seasons":              None,
            "total_runtime":        None,
            "certification":        None,
            "keywords":             [],
            "cast_names":           [],
            "director_names":       [],
            "writer_names":         [],
            "studio_names":         [],
            "available_on":         [],
            "rent_on":              [],
            "buy_on":               [],
            "providers_fetched":    False,
            "status":               None,
            "production_countries": [],
            "spoken_languages":     [],
            "franchises":           [],
            "themes":               [],
            "aliases":              [],
            "collections":          [],
        },
    }


async def bulk_import_catalog(
    db,
    pages_general:  int = 10,
    pages_genre:    int = 5,
    pages_provider: int = 3,
) -> dict:
    """Fetch all TMDB endpoints with full pagination and upsert to movies_cache.

    Parameters
    ----------
    pages_general : int
        Pages to fetch per general endpoint (popular/trending/top_rated).
        Each TMDB page = 20 items, max 500 pages.
    pages_genre : int
        Pages to fetch per genre-specific discover endpoint.
        Lower than pages_general by default because there are ~100 genre
        endpoints, so total coverage is already very wide.

    Estimated totals at defaults (pages_general=10, pages_genre=5):
      General:  11 endpoints × 10 pages = 110 requests  → ~2 200 raw items
      Genre:   ~100 endpoints ×  5 pages = 500 requests  → ~10 000 raw items
      Total:   610 requests → ~12 200 raw → ~6 000–10 000 unique titles

    The upsert uses $setOnInsert for provider/enrichment fields so previously-
    fetched provider data is never overwritten by a later import pass.
    """
    # Stay well within TMDB's burst limit (40 req/s recommended, max 50/s)
    sem    = asyncio.Semaphore(12)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)

    # Build all (kind, path, page, extra) tasks in one flat list
    general_tasks = [
        (kind, path, page, extra)
        for kind, path, extra in GENERAL_ENDPOINTS
        for page in range(1, pages_general + 1)
    ]
    genre_tasks = [
        (kind, path, page, extra)
        for kind, path, extra in GENRE_ENDPOINTS
        for page in range(1, pages_genre + 1)
    ]
    provider_tasks = [
        (kind, path, page, extra)
        for kind, path, extra in PROVIDER_ENDPOINTS
        for page in range(1, pages_provider + 1)
    ] if pages_provider > 0 else []
    all_tasks = general_tasks + genre_tasks + provider_tasks

    logger.info(
        f"Bulk import starting: {len(GENERAL_ENDPOINTS)} general × {pages_general} pages "
        f"+ {len(GENRE_ENDPOINTS)} genre × {pages_genre} pages "
        f"+ {len(PROVIDER_ENDPOINTS)} provider-region × {pages_provider} pages "
        f"= {len(all_tasks)} HTTP requests"
    )

    async with httpx.AsyncClient(timeout=20.0, limits=limits) as client:
        coros = [
            _fetch_page(client, sem, kind, path, page, extra)
            for kind, path, page, extra in all_tasks
        ]
        page_results = await asyncio.gather(*coros, return_exceptions=True)

    # ── Enrich raw items ─────────────────────────────────────────────────────
    raw: list[dict] = []
    for result in page_results:
        if isinstance(result, Exception):
            continue
        kind, items = result
        for item in items:
            enriched = _light_enrich(item, kind)
            if enriched:
                raw.append(enriched)

    # ── Deduplicate: highest-popularity copy wins ────────────────────────────
    seen_ids: set[str] = set()
    deduped:  list[dict] = []
    for m in sorted(raw, key=lambda x: x["popularity"], reverse=True):
        if m["id"] not in seen_ids:
            seen_ids.add(m["id"])
            deduped.append(m)

    logger.info(f"Bulk import: {len(raw)} raw → {len(deduped)} unique titles after dedup")

    if not deduped:
        return {"unique": 0, "total_in_db": 0, "genre_coverage": {}}

    # ── Log genre coverage ───────────────────────────────────────────────────
    genre_counter: Counter = Counter()
    for m in deduped:
        for g in (m.get("genres") or []):
            genre_counter[g] += 1
    coverage_str = " | ".join(f"{g}:{n}" for g, n in sorted(genre_counter.items()))
    logger.info(f"Genre coverage in import batch: {coverage_str}")

    # ── Upsert to MongoDB ────────────────────────────────────────────────────
    # $set refreshes metadata fields that may have changed (rating, vote_count, etc.)
    # $setOnInsert only runs on NEW documents so enriched provider data is preserved.
    ops = [
        UpdateOne(
            {"id": m["id"]},
            _catalog_update_document(m),
            upsert=True,
        )
        for m in deduped
    ]

    CHUNK = 500
    for i in range(0, len(ops), CHUNK):
        try:
            await db.movies_cache.bulk_write(ops[i:i + CHUNK], ordered=False)
        except Exception as exc:
            logger.warning(f"bulk_write chunk {i // CHUNK}: {type(exc).__name__}: {exc}")

    total_in_db = await db.movies_cache.count_documents({})
    logger.info(f"Catalog import complete — {total_in_db} total titles in DB")

    return {
        "unique":         len(deduped),
        "total_in_db":    total_in_db,
        "genre_coverage": dict(genre_counter.most_common()),
    }


async def enrich_providers_top(db, limit: int = 500, region: str = "GB") -> int:
    """Fetch streaming provider data for the top-N un-enriched titles by popularity.

    Runs as a background task after bulk_import_catalog so the most-popular
    titles quickly get accurate available_on / rent_on / buy_on data.

    Uses $set (not $setOnInsert) so stale provider data can be refreshed on
    subsequent passes, but only for titles where the TMDB API actually succeeded.
    Titles where the API call fails are left with providers_fetched=False so
    the next pass will retry them.
    """
    cursor = db.movies_cache.find(
        {"providers_fetched": {"$ne": True}},
        {"_id": 0, "id": 1, "tmdb_id": 1, "type": 1},
    ).sort("popularity", -1).limit(limit)
    items = await cursor.to_list(length=limit)

    if not items:
        logger.info("Provider enrichment: nothing left to enrich")
        return 0

    # 6 concurrent provider requests ≈ 30 req/s — safely under TMDB's 40 req/s burst.
    # The previous value of 10 caused 429 errors during large enrichment passes.
    sem    = asyncio.Semaphore(6)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=6)

    async def _get_providers(client: httpx.AsyncClient, item: dict):
        kind     = item.get("type", "movie")
        tmdb_id  = item.get("tmdb_id")
        movie_id = item["id"]
        if not tmdb_id:
            return movie_id, {}, False
        async with sem:
            try:
                r = await client.get(
                    f"{TMDB_BASE}/{kind}/{tmdb_id}/watch/providers",
                    headers=_headers(),
                    timeout=15.0,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                logger.debug(f"Provider fetch {movie_id}: {exc}")
                return movie_id, {}, False

        region_data = (data.get("results") or {}).get(region) or {}
        out: dict[str, set] = {"flatrate": set(), "rent": set(), "buy": set()}
        bucket_map = {
            "flatrate": "flatrate", "ads": "flatrate", "free": "flatrate",
            "rent":     "rent",     "buy": "buy",
        }
        for src, dst in bucket_map.items():
            for entry in (region_data.get(src) or []):
                mapped = PROVIDER_MAP.get(entry.get("provider_id"))
                if mapped:
                    out[dst].add(mapped)
                elif entry.get("provider_name"):
                    norm = normalize_provider(entry["provider_name"])
                    if dst == "flatrate":
                        # Flatrate = our subscription services only. Keep aliases
                        # that resolve to a known service (Max/HBO→hbo_max) but
                        # drop unknown flatrate storefronts (e.g. "YouTube TV").
                        if norm in KNOWN_SERVICE_IDS:
                            out[dst].add(norm)
                    else:
                        # Rent/buy keep the (normalized) raw name even if it's not
                        # one of our subscription services.
                        out[dst].add(norm)
        return movie_id, {k: sorted(v) for k, v in out.items()}, True

    async with httpx.AsyncClient(timeout=15.0, limits=limits) as client:
        results = await asyncio.gather(
            *[_get_providers(client, item) for item in items],
            return_exceptions=True,
        )

    ops: list[UpdateOne] = []
    enriched_count = 0
    failed_count   = 0
    for result in results:
        if isinstance(result, Exception):
            continue
        movie_id, providers, ok = result
        if ok:
            enriched_count += 1
            entry = build_region_entry(
                providers.get("flatrate", []),
                providers.get("rent",     []),
                providers.get("buy",      []),
            )
            # Canonical region-keyed store — always written.
            set_fields = {
                f"providers_by_region.{region}": entry,
            }
            # Flat fields + global flags mirror the DEFAULT_REGION only, so the
            # in-memory engine (which reads flat fields) stays on a single,
            # consistent region and non-default refreshes never corrupt it.
            if region == DEFAULT_REGION:
                set_fields.update({
                    "available_on":              entry["available_on"],
                    "rent_on":                   entry["rent_on"],
                    "buy_on":                    entry["buy_on"],
                    "providers_fetched":         True,
                    "providers_fetched_at":      entry["fetched_at"],
                    "providers_region":          region,
                    "providers_empty_confirmed": entry["empty_confirmed"],
                    "provider_confidence":       entry["confidence"],
                })
            ops.append(UpdateOne({"id": movie_id}, {"$set": set_fields}))
        else:
            # API call failed — leave providers_fetched=False so next pass retries.
            # Integrity: a failed/rate-limited fetch must NEVER be recorded as
            # success or confirmed-empty.
            failed_count += 1

    if ops:
        for i in range(0, len(ops), 500):
            try:
                await db.movies_cache.bulk_write(ops[i:i + 500], ordered=False)
            except Exception as exc:
                logger.warning(f"Provider enrichment write: {exc}")

    logger.info(
        f"Provider enrichment pass done: {enriched_count}/{len(items)} enriched "
        f"({failed_count} TMDB errors, will retry)"
    )
    return enriched_count
