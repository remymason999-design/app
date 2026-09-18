"""TMDB integration: fetch popular movies/shows + streaming availability."""
import os
import logging
import asyncio
import time
from collections import OrderedDict
from typing import List, Optional

import httpx

logger = logging.getLogger("watchsmart.tmdb")

TMDB_BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"
_SEASON_CACHE_MAX = 256
_SEASON_CACHE_TTL = 6 * 60 * 60
_SEASON_FAILURE_TTL = 5 * 60
_SEASON_FETCH_LIMIT = 30
_season_cache: OrderedDict[tuple[int, int], tuple[float, Optional[dict]]] = OrderedDict()
_season_cache_lock = asyncio.Lock()
_season_fetch_semaphore = asyncio.Semaphore(8)

# Map TMDB watch-provider ids → our service ids
# Source: https://developer.themoviedb.org/reference/watch-providers-list
PROVIDER_MAP = {
    8: "netflix",
    337: "disney_plus",
    1899: "hbo_max",   # Max (US)
    384: "hbo_max",    # legacy HBO Max (US)
    1825: "hbo_max",   # HBO Max Amazon Channel (GB / EU re-distributed Max)
    9: "prime_video",
    119: "prime_video",
    350: "apple_tv",
    15: "hulu",
    531: "paramount",
    386: "peacock",
    387: "peacock",
}


def _headers() -> dict:
    token = os.environ.get("TMDB_BEARER_TOKEN")
    if not token:
        raise RuntimeError("TMDB_BEARER_TOKEN missing")
    return {"Authorization": f"Bearer {token}", "accept": "application/json"}


def _img(path: Optional[str], size: str = "w780") -> Optional[str]:
    return f"{IMG_BASE}/{size}{path}" if path else None


async def _get(client: httpx.AsyncClient, path: str, params: Optional[dict] = None) -> dict:
    r = await client.get(f"{TMDB_BASE}{path}", params=params or {}, headers=_headers(), timeout=15.0)
    r.raise_for_status()
    return r.json()


async def _get_with_retry(client: httpx.AsyncClient, path: str, retries: int = 2) -> dict:
    """Fetch a lazy detail endpoint with a small, bounded retry budget."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            return await _get(client, path)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(0.15 * (2 ** attempt))
    raise last_error


async def fetch_tv_season(tmdb_id: int, season_number: int) -> Optional[dict]:
    """Return stable episode metadata for one non-special TV season.

    Cache size, TTL and retries are deliberately bounded so Library requests
    cannot create an unbounded TMDB fan-out or retain stale release data forever.
    """
    if int(tmdb_id) <= 0 or int(season_number) <= 0:
        return None
    key = (int(tmdb_id), int(season_number))
    now = time.monotonic()
    async with _season_cache_lock:
        cached = _season_cache.get(key)
        ttl = _SEASON_CACHE_TTL if cached and cached[1] else _SEASON_FAILURE_TTL
        if cached and now - cached[0] < ttl:
            _season_cache.move_to_end(key)
            return dict(cached[1]) if cached[1] else None
        if cached:
            _season_cache.pop(key, None)
    try:
        async with _season_fetch_semaphore:
            async with httpx.AsyncClient(timeout=10.0) as client:
                raw = await _get_with_retry(client, f"/tv/{key[0]}/season/{key[1]}")
    except Exception as exc:
        logger.warning("TMDB season hydration failed tv=%s season=%s: %s", *key, exc)
        async with _season_cache_lock:
            _season_cache[key] = (time.monotonic(), None)
            _season_cache.move_to_end(key)
            while len(_season_cache) > _SEASON_CACHE_MAX:
                _season_cache.popitem(last=False)
        return None
    episodes = []
    for episode in raw.get("episodes") or []:
        number = int(episode.get("episode_number") or 0)
        if number <= 0:
            continue
        runtime = episode.get("runtime")
        runtime = int(runtime) if isinstance(runtime, (int, float)) and runtime > 0 else None
        episodes.append({
            "id": f"tmdb_tv_{key[0]}_s{key[1]:02d}e{number:03d}",
            "episode_key": f"s{key[1]:02d}e{number:03d}",
            "tmdb_episode_id": episode.get("id"),
            "season_number": key[1],
            "episode_number": number,
            "name": episode.get("name"),
            "air_date": episode.get("air_date") or None,
            "air_date_provenance": "tmdb" if episode.get("air_date") else "unknown",
            "runtime": runtime,
            "runtime_provenance": "tmdb_episode" if runtime else "unknown",
        })
    result = {
        "season_number": key[1],
        "name": raw.get("name"),
        "air_date": raw.get("air_date") or None,
        "air_date_provenance": "tmdb" if raw.get("air_date") else "unknown",
        "episodes": episodes,
        "episode_count": len(episodes),
        "metadata_provenance": "tmdb_season",
    }
    async with _season_cache_lock:
        _season_cache[key] = (time.monotonic(), result)
        _season_cache.move_to_end(key)
        while len(_season_cache) > _SEASON_CACHE_MAX:
            _season_cache.popitem(last=False)
    return dict(result)


async def hydrate_tv_seasons(tmdb_id: int, seasons: list | None) -> list:
    """Hydrate known seasons concurrently, with a hard per-series bound."""
    season_numbers = sorted({
        int(s.get("season_number") or 0) for s in (seasons or [])
        if isinstance(s, dict) and int(s.get("season_number") or 0) > 0
    })[:_SEASON_FETCH_LIMIT]
    semaphore = asyncio.Semaphore(4)

    async def fetch(number: int):
        async with semaphore:
            return await fetch_tv_season(tmdb_id, number)

    hydrated = await asyncio.gather(*(fetch(n) for n in season_numbers))
    by_number = {int(s.get("season_number") or 0): dict(s) for s in (seasons or [])
                 if isinstance(s, dict)}
    for number in set(by_number) - set(season_numbers):
        if number > 0:
            by_number[number]["metadata_provenance"] = "tmdb_season_unavailable"
    for number, season in zip(season_numbers, hydrated):
        if season:
            by_number[season["season_number"]] = {
                **by_number.get(season["season_number"], {}), **season
            }
        elif number in by_number:
            by_number[number]["metadata_provenance"] = "tmdb_season_unavailable"
    return [by_number[n] for n in sorted(by_number) if n > 0]


async def _providers_for(
    client: httpx.AsyncClient, kind: str, tmdb_id: int, region: str,
    raise_on_error: bool = False,
) -> dict:
    """Returns {'flatrate': [service_ids], 'rent': [service_ids], 'buy': [service_ids]}.

    When raise_on_error is True the underlying HTTP error propagates so callers
    can distinguish a genuine "no providers" answer from a network/rate-limit
    failure (critical for not poisoning the cache with false empties).
    """
    from providers_util import normalize_provider, KNOWN_SERVICE_IDS
    try:
        data = await _get(client, f"/{kind}/{tmdb_id}/watch/providers")
    except Exception:
        if raise_on_error:
            raise
        return {"flatrate": [], "rent": [], "buy": []}
    region_data = data.get("results", {}).get(region) or {}
    out = {"flatrate": set(), "rent": set(), "buy": set()}
    bucket_map = {"flatrate": "flatrate", "ads": "flatrate", "free": "flatrate", "rent": "rent", "buy": "buy"}
    for src, dst in bucket_map.items():
        for entry in region_data.get(src, []) or []:
            mapped = PROVIDER_MAP.get(entry.get("provider_id"))
            if mapped:
                out[dst].add(mapped)
            elif entry.get("provider_name"):
                # Normalize raw names (Max/HBO/Amazon Video aliases) so the same
                # service never appears under multiple labels.
                norm = normalize_provider(entry["provider_name"])
                if dst == "flatrate":
                    # Flatrate = our subscription services only; drop unknown
                    # flatrate storefronts but keep alias→known mappings.
                    if norm in KNOWN_SERVICE_IDS:
                        out[dst].add(norm)
                else:
                    out[dst].add(norm)
    return {k: sorted(v) for k, v in out.items()}


async def _trailer_for(client: httpx.AsyncClient, kind: str, tmdb_id: int) -> Optional[str]:
    try:
        data = await _get(client, f"/{kind}/{tmdb_id}/videos")
    except Exception:
        return None
    videos = data.get("results", []) or []
    # Prefer official YouTube Trailer
    def score(v):
        s = 0
        if v.get("site") == "YouTube":
            s += 10
        if v.get("type") == "Trailer":
            s += 5
        if v.get("type") == "Teaser":
            s += 2
        if v.get("official"):
            s += 3
        return s
    videos.sort(key=score, reverse=True)
    for v in videos:
        if v.get("site") == "YouTube" and v.get("key"):
            return v["key"]
    return None


async def _enrich(client: httpx.AsyncClient, item: dict, kind: str, region: str) -> Optional[dict]:
    tmdb_id = item.get("id")
    is_movie = kind == "movie"
    title = item.get("title") if is_movie else item.get("name")
    date = item.get("release_date") if is_movie else item.get("first_air_date")
    if not tmdb_id or not title or not date:
        return None
    # Skip items with no poster — they render as broken cards on the frontend.
    if not item.get("poster_path"):
        return None
    # One-shot detail fetch with keywords + certifications + credits appended.
    # `credits` gives us cast (actors) and crew (incl. director) in a single call.
    try:
        if is_movie:
            detail = await _get(client, f"/{kind}/{tmdb_id}", {
                "append_to_response": "keywords,release_dates,credits,alternative_titles",
            })
        else:
            detail = await _get(client, f"/{kind}/{tmdb_id}", {
                "append_to_response": "keywords,content_ratings,credits,aggregate_credits,alternative_titles",
            })
    except Exception:
        return None

    providers = await _providers_for(client, kind, tmdb_id, region)
    if not providers["flatrate"] and not providers["rent"] and not providers["buy"]:
        return None

    trailer = await _trailer_for(client, kind, tmdb_id)

    if is_movie:
        runtime = detail.get("runtime") or 0
        seasons = None
        total_runtime = runtime
    else:
        ep_runs = detail.get("episode_run_time") or []
        runtime = ep_runs[0] if ep_runs else 45
        seasons = [
            {"season_number": s.get("season_number"), "name": s.get("name"),
             "episode_count": s.get("episode_count"), "air_date": s.get("air_date"),
             "poster_path": _img(s.get("poster_path"), "w342") if s.get("poster_path") else None}
            for s in (detail.get("seasons") or []) if s.get("season_number", 0) > 0
        ]
        total_eps = sum(s.get("episode_count") or 0 for s in seasons)
        total_runtime = total_eps * runtime

    genres = [g["name"] for g in (detail.get("genres") or [])]
    rename = {
        "Science Fiction": "Sci-Fi",
        "Sci-Fi & Fantasy": "Sci-Fi",
        "Action & Adventure": "Action",
        "War & Politics": "Drama",
    }
    genres = [rename.get(g, g) for g in genres]

    # Detect category tags for filtering (anime, bollywood, etc.)
    tags = set()
    countries = []
    raw_origin = detail.get("origin_country") or []
    if raw_origin and isinstance(raw_origin[0], str):
        countries = list(raw_origin)
    else:
        countries = [c.get("iso_3166_1") for c in (detail.get("production_countries") or []) if isinstance(c, dict)]
    countries = [c for c in countries if c]
    if "Animation" in genres and ("JP" in countries or detail.get("original_language") == "ja"):
        tags.add("anime")
    if "IN" in countries or detail.get("original_language") == "hi":
        tags.add("bollywood")
    if detail.get("original_language") and detail.get("original_language") not in ("en",):
        tags.add(f"lang:{detail['original_language']}")

    # ---- Certification (region-specific, fall back to US) ----
    certification: Optional[str] = None
    if is_movie:
        for entry in (detail.get("release_dates") or {}).get("results") or []:
            if entry.get("iso_3166_1") == region:
                for r in entry.get("release_dates") or []:
                    if r.get("certification"):
                        certification = r["certification"]
                        break
            if certification:
                break
        if not certification:
            for entry in (detail.get("release_dates") or {}).get("results") or []:
                if entry.get("iso_3166_1") == "GB":
                    for r in entry.get("release_dates") or []:
                        if r.get("certification"):
                            certification = r["certification"]
                            break
                if certification:
                    break
    else:
        for entry in (detail.get("content_ratings") or {}).get("results") or []:
            if entry.get("iso_3166_1") == region and entry.get("rating"):
                certification = entry["rating"]
                break
        if not certification:
            for entry in (detail.get("content_ratings") or {}).get("results") or []:
                if entry.get("iso_3166_1") == "GB" and entry.get("rating"):
                    certification = entry["rating"]
                    break

    # ---- Keywords (canonical TMDB taxonomy, very useful for theme detection) ----
    kw_root = detail.get("keywords") or {}
    raw_keywords = kw_root.get("keywords") if is_movie else kw_root.get("results")
    keywords: list[str] = []
    if isinstance(raw_keywords, list):
        keywords = [k.get("name") for k in raw_keywords if k.get("name")][:30]

    # ---- Credits: cast names + director(s) ----------------------------------
    # For movies the "credits" object holds cast+crew. For TV the same payload
    # exists under "credits"; we additionally fetch "aggregate_credits" which
    # gives series-wide casting (more accurate than a single-episode credit).
    credits_root = (detail.get("aggregate_credits")
                    if not is_movie and detail.get("aggregate_credits")
                    else (detail.get("credits") or {}))
    raw_cast = credits_root.get("cast") or []
    cast_names = [c.get("name") for c in raw_cast if c.get("name")][:15]
    raw_crew = credits_root.get("crew") or []
    director_names: list[str] = []
    DIRECTOR_JOBS = {"Director", "Series Director"}
    for c in raw_crew:
        # /credits exposes top-level `job`; aggregate_credits exposes `jobs[]`.
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
    if not is_movie:
        for creator in (detail.get("created_by") or []):
            n = creator.get("name")
            if n and n not in director_names:
                director_names.append(n)
    director_names = director_names[:5]

    # ---- Writers (screenplay / story) ---------------------------------------
    writer_names: list[str] = []
    WRITER_JOBS = {"Writer", "Screenwriter", "Story", "Novel", "Author"}
    for c in raw_crew:
        job_titles: set = set()
        if c.get("job"):
            job_titles.add(c["job"])
        for j in (c.get("jobs") or []):
            jn = (j or {}).get("job")
            if jn:
                job_titles.add(jn)
        if job_titles & WRITER_JOBS:
            n = c.get("name")
            if n and n not in writer_names:
                writer_names.append(n)
    writer_names = writer_names[:5]

    # ---- Production companies / studios -------------------------------------
    studio_names = [
        c.get("name") for c in (detail.get("production_companies") or [])
        if c.get("name")
    ][:8]

    # ---- Collection / franchise (movies only) -------------------------------
    # Used by content_cards to seed superhero/space-opera/etc. themes
    # directly from franchise membership (Task #8).
    collection_name = None
    collection_id = None
    if is_movie:
        bcoll = detail.get("belongs_to_collection")
        if isinstance(bcoll, dict):
            collection_id = bcoll.get("id")
            collection_name = bcoll.get("name")

    # ---- Aliases (alt / original / regional titles) ------------------------
    alt_root = detail.get("alternative_titles") or {}
    raw_alts = alt_root.get("titles") if is_movie else alt_root.get("results")
    aliases: list[str] = []
    if isinstance(raw_alts, list):
        _seen: set = set()
        for a in raw_alts:
            t = (a or {}).get("title")
            if t and t not in _seen:
                _seen.add(t)
                aliases.append(t)
        aliases = aliases[:20]
    orig = detail.get("original_title") if is_movie else detail.get("original_name")
    if orig and orig not in aliases:
        aliases.insert(0, orig)
        aliases = aliases[:20]

    # ---- Collections / franchises ------------------------------------------
    collections: list[str] = []
    btc = detail.get("belongs_to_collection")
    if isinstance(btc, dict) and btc.get("name"):
        collections.append(btc["name"])

    return {
        "id": f"tmdb_{kind}_{tmdb_id}",
        "tmdb_id": tmdb_id,
        "title": title,
        "year": int(date[:4]),
        "rating": round(float(detail.get("vote_average") or 0), 1),
        "vote_count": detail.get("vote_count") or 0,
        "runtime": runtime,
        "total_runtime": total_runtime,
        "seasons": seasons,
        "genres": genres,
        "tags": sorted(tags),
        "type": "movie" if is_movie else "tv",
        "overview": detail.get("overview") or "",
        "poster_url": _img(detail.get("poster_path"), "w780"),
        "backdrop_url": _img(detail.get("backdrop_path"), "w1280"),
        "trailer_youtube_id": trailer,
        "available_on": providers["flatrate"],
        "rent_on": providers["rent"],
        "buy_on": providers["buy"],
        "popularity": detail.get("popularity") or 0,
        "original_language": detail.get("original_language"),
        "certification": certification,
        "keywords": keywords,
        "cast_names": cast_names,
        "director_names": director_names,
        "writer_names": writer_names,
        "studio_names": studio_names,
        "collection_id": collection_id,
        "collection_name": collection_name,
        "origin_country": countries,
        "aliases": aliases,
        "collections": collections,
    }


async def search_titles(query: str, region: str = "GB", limit: int = 20) -> List[dict]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            multi = await _get(client, "/search/multi", {"query": query, "include_adult": False, "page": 1})
        except Exception:
            return []
        results = []
        for r in (multi.get("results") or [])[:limit]:
            kind = r.get("media_type")
            if kind not in ("movie", "tv"):
                continue
            enriched = await _enrich(client, r, kind, region)
            if enriched:
                results.append(enriched)
        return results


async def fetch_endpoint(endpoint_path: str, kind: str, pages: int = 1, region: str = "GB") -> List[dict]:
    """Fetch one TMDB list endpoint and enrich."""
    import asyncio
    out = []
    async with httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20)) as client:
        for page in range(1, pages + 1):
            try:
                data = await _get(client, endpoint_path, {"page": page, "region": region})
            except Exception:
                continue
            items = (data.get("results") or [])[:20]
            results = await asyncio.gather(
                *[_enrich(client, item, kind, region) for item in items],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, dict):
                    out.append(r)
    seen = set()
    deduped = []
    for m in out:
        if m["id"] not in seen:
            seen.add(m["id"])
            deduped.append(m)
    return deduped


async def fetch_similar(kind: str, tmdb_id: int, region: str = "GB", limit: int = 12) -> List[dict]:
    import asyncio
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            data = await _get(client, f"/{kind}/{tmdb_id}/similar")
        except Exception:
            return []
        items = (data.get("results") or [])[:limit]
        results = await asyncio.gather(
            *[_enrich(client, item, kind, region) for item in items],
            return_exceptions=True,
        )
        return [r for r in results if isinstance(r, dict)]


async def fetch_trailer(kind: str, tmdb_id: int) -> Optional[str]:
    """Fetch the best YouTube trailer key for a title on demand. Returns key or None."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await _trailer_for(client, kind, tmdb_id)


async def fetch_providers(kind: str, tmdb_id: int, region: str = "GB") -> dict:
    """Fetch streaming provider data on-demand for a single title.

    Returns {'flatrate': [...], 'rent': [...], 'buy': [...], 'ok': bool}.

    `ok` is True only when TMDB actually responded.  On any network/rate-limit
    error `ok` is False and the lists are empty — callers MUST check `ok` before
    recording the result as "fetched" or "confirmed empty", otherwise a transient
    failure would be cached as a false "not available anywhere".
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            providers = await _providers_for(
                client, kind, tmdb_id, region, raise_on_error=True
            )
        providers["ok"] = True
        return providers
    except Exception:
        return {"flatrate": [], "rent": [], "buy": [], "ok": False}


async def fetch_tmdb_reviews(kind: str, tmdb_id: int, limit: int = 5) -> List[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            data = await _get(client, f"/{kind}/{tmdb_id}/reviews")
        except Exception:
            return []
        out = []
        for r in (data.get("results") or [])[:limit]:
            details = r.get("author_details") or {}
            out.append({
                "source": "tmdb",
                "author": r.get("author") or details.get("username") or "Anonymous",
                "rating": details.get("rating"),
                "content": r.get("content") or "",
                "created_at": r.get("created_at"),
                "url": r.get("url"),
            })
        return out


async def fetch_catalog(pages: int = 5, region: Optional[str] = None) -> List[dict]:
    """Fetch a deep catalog from TMDB across many endpoints + pages.

    Sources harvested per kind (movie, tv):
      * /{kind}/popular        — popularity sort
      * /{kind}/top_rated      — rating sort
      * /trending/{kind}/week  — current cultural moment
      * /discover/{kind}       — sort_by=primary_release_date.desc (freshness)
      * /discover/{kind}       — sort_by=vote_count.desc (depth: well-rated catalog)

    With pages=8 this typically yields 1500-2500 unique titles after dedup,
    well above the engine's TARGET_POOL = 2000.
    """
    region = (region or os.environ.get("TMDB_REGION", "GB")).upper()
    out: List[dict] = []
    endpoints: list[tuple[str, str, dict]] = []
    for kind in ("movie", "tv"):
        endpoints.append((kind, f"/{kind}/popular", {}))
        endpoints.append((kind, f"/{kind}/top_rated", {}))
        endpoints.append((kind, f"/trending/{kind}/week", {}))
        # Deep discovery sorts — freshest releases first
        date_field = "primary_release_date.desc" if kind == "movie" else "first_air_date.desc"
        endpoints.append((kind, f"/discover/{kind}", {
            "sort_by": date_field,
            "vote_count.gte": 100,
        }))
        # Deep discovery sorts — quality-weighted breadth
        endpoints.append((kind, f"/discover/{kind}", {
            "sort_by": "vote_count.desc",
        }))

    import asyncio
    async with httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20)) as client:
        for kind, ep, extra in endpoints:
            for page in range(1, pages + 1):
                try:
                    params = {"page": page}
                    if "popular" in ep and kind == "movie":
                        params["region"] = region
                    params.update(extra)
                    data = await _get(client, ep, params)
                except Exception as e:
                    logger.warning(f"TMDB {ep} p{page} failed: {e}")
                    continue
                items = (data.get("results") or [])[:20]
                results = await asyncio.gather(
                    *[_enrich(client, item, kind, region) for item in items],
                    return_exceptions=True,
                )
                for r in results:
                    if isinstance(r, dict):
                        out.append(r)
    seen = set()
    deduped = []
    for m in out:
        if m["id"] not in seen:
            seen.add(m["id"])
            deduped.append(m)
    deduped.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return deduped
