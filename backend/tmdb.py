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


async def _providers_for(client: httpx.AsyncClient, kind: str, tmdb_id: int, region: str) -> dict:
    """Returns {'flatrate': [service_ids], 'rent': [service_ids], 'buy': [service_ids]}."""
    try:
        data = await _get(client, f"/{kind}/{tmdb_id}/watch/providers")
    except Exception:
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
                # For rent/buy keep the raw name even if not in our subscription list
                if dst in ("rent", "buy"):
                    out[dst].add(entry["provider_name"])
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
    # One-shot detail fetch with keywords + certifications appended
    try:
        if is_movie:
            detail = await _get(client, f"/{kind}/{tmdb_id}", {
                "append_to_response": "keywords,release_dates",
            })
        else:
            detail = await _get(client, f"/{kind}/{tmdb_id}", {
                "append_to_response": "keywords,content_ratings",
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
                if entry.get("iso_3166_1") == "US":
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
                if entry.get("iso_3166_1") == "US" and entry.get("rating"):
                    certification = entry["rating"]
                    break

    # ---- Keywords (canonical TMDB taxonomy, very useful for theme detection) ----
    kw_root = detail.get("keywords") or {}
    raw_keywords = kw_root.get("keywords") if is_movie else kw_root.get("results")
    keywords: list[str] = []
    if isinstance(raw_keywords, list):
        keywords = [k.get("name") for k in raw_keywords if k.get("name")][:30]

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
    region = (region or os.environ.get("TMDB_REGION", "US")).upper()
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
