"""TMDB integration: fetch popular movies/shows + streaming availability."""
import os
import logging
from typing import List, Optional

import httpx

logger = logging.getLogger("watchsmart.tmdb")

TMDB_BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"

# Map TMDB watch-provider ids → our service ids
# Source: https://developer.themoviedb.org/reference/watch-providers-list
PROVIDER_MAP = {
    8: "netflix",
    337: "disney_plus",
    1899: "hbo_max",   # Max
    384: "hbo_max",    # legacy HBO Max
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


async def _providers_for(client: httpx.AsyncClient, kind: str, tmdb_id: int, region: str) -> List[str]:
    try:
        data = await _get(client, f"/{kind}/{tmdb_id}/watch/providers")
    except Exception:
        return []
    region_data = data.get("results", {}).get(region) or {}
    found = set()
    for bucket in ("flatrate", "ads", "free"):
        for entry in region_data.get(bucket, []) or []:
            mapped = PROVIDER_MAP.get(entry.get("provider_id"))
            if mapped:
                found.add(mapped)
    return sorted(found)


async def _trailer_for(client: httpx.AsyncClient, kind: str, tmdb_id: int) -> Optional[str]:
    try:
        data = await _get(client, f"/{kind}/{tmdb_id}/videos")
    except Exception:
        return None
    videos = data.get("results", []) or []
    # Prefer official YouTube Trailer
    def score(v):
        s = 0
        if v.get("site") == "YouTube": s += 10
        if v.get("type") == "Trailer": s += 5
        if v.get("type") == "Teaser": s += 2
        if v.get("official"): s += 3
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
    # Fetch detail (for genres + runtime)
    try:
        detail = await _get(client, f"/{kind}/{tmdb_id}")
    except Exception:
        return None

    providers = await _providers_for(client, kind, tmdb_id, region)
    if not providers:
        # Skip titles with no streaming availability — useless for our app
        return None

    trailer = await _trailer_for(client, kind, tmdb_id)
    if not trailer:
        return None

    if is_movie:
        runtime = detail.get("runtime") or 0
    else:
        ep_runs = detail.get("episode_run_time") or []
        runtime = ep_runs[0] if ep_runs else 45

    genres = [g["name"] for g in (detail.get("genres") or [])]
    # Normalise some TMDB names to match our onboarding genre list
    rename = {
        "Science Fiction": "Sci-Fi",
        "Sci-Fi & Fantasy": "Sci-Fi",
        "Action & Adventure": "Action",
        "War & Politics": "Drama",
    }
    genres = [rename.get(g, g) for g in genres]

    return {
        "id": f"tmdb_{kind}_{tmdb_id}",
        "tmdb_id": tmdb_id,
        "title": title,
        "year": int(date[:4]),
        "rating": round(float(detail.get("vote_average") or 0), 1),
        "runtime": runtime,
        "genres": genres,
        "type": "movie" if is_movie else "tv",
        "overview": detail.get("overview") or "",
        "poster_url": _img(detail.get("poster_path"), "w780"),
        "backdrop_url": _img(detail.get("backdrop_path"), "w1280"),
        "trailer_youtube_id": trailer,
        "available_on": providers,
        "popularity": detail.get("popularity") or 0,
    }


async def fetch_catalog(pages: int = 5, region: Optional[str] = None) -> List[dict]:
    """Fetch popular + top-rated + trending movies/TV, enriched with providers & trailers."""
    region = (region or os.environ.get("TMDB_REGION", "US")).upper()
    out: List[dict] = []
    # Endpoints to harvest from for breadth
    endpoints = []
    for kind in ("movie", "tv"):
        for path in ("popular", "top_rated"):
            endpoints.append((kind, f"/{kind}/{path}"))
        endpoints.append((kind, f"/trending/{kind}/week"))

    # Use a long-lived client and concurrent enrichment
    import asyncio
    async with httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20)) as client:
        for kind, ep in endpoints:
            for page in range(1, pages + 1):
                try:
                    params = {"page": page}
                    if "popular" in ep and kind == "movie":
                        params["region"] = region
                    data = await _get(client, ep, params)
                except Exception as e:
                    logger.warning(f"TMDB {ep} p{page} failed: {e}")
                    continue
                items = (data.get("results") or [])[:20]
                # Concurrent enrichment per page (TMDB allows 50 req/s)
                results = await asyncio.gather(
                    *[_enrich(client, item, kind, region) for item in items],
                    return_exceptions=True,
                )
                for r in results:
                    if isinstance(r, dict):
                        out.append(r)
    # Deduplicate by id
    seen = set()
    deduped = []
    for m in out:
        if m["id"] not in seen:
            seen.add(m["id"])
            deduped.append(m)
    deduped.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    return deduped
