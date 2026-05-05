"""Content router: movies/{id}, /search, /search/suggest, similar."""
import os
from fastapi import APIRouter, Depends, HTTPException

from core import (
    db, require_user, get_catalog, find_movie, tmdb_client, logger,
    apply_user_filters,
)
from content_cards import build_card, card_similarity

router = APIRouter(tags=["content"])


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: str, user: dict = Depends(require_user)):
    m = find_movie(movie_id)
    if not m:
        m = await db.movies_cache.find_one({"id": movie_id}, {"_id": 0})
    if not m:
        raise HTTPException(404, "Movie not found")
    out = dict(m)
    # Ensure a content card is present (compute on demand for cold cache hits)
    if not out.get("card"):
        out["card"] = build_card(out)
    progress = (user.get("progress") or {}).get(movie_id)
    if progress:
        out["progress"] = progress
    return out


def _local_search(q: str, limit: int = 20):
    ql = (q or "").strip().lower()
    if not ql:
        return []
    results = []
    for m in get_catalog():
        title = (m.get("title") or "").lower()
        genres = [g.lower() for g in (m.get("genres") or [])]
        if ql in title or ql in genres:
            results.append(m)
            continue
        # Typo tolerance: very short edit distance for short queries
        if len(ql) >= 4:
            for word in title.split():
                if abs(len(word) - len(ql)) <= 1 and _close_match(ql, word):
                    results.append(m)
                    break
    return results[:limit]


def _close_match(a: str, b: str) -> bool:
    """Lightweight Levenshtein-ish: allow 1 char difference for words >= 4 chars."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    diffs = 0
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            diffs += 1
            if diffs > 1:
                return False
            if len(a) > len(b):
                i += 1
            elif len(b) > len(a):
                j += 1
            else:
                i += 1
                j += 1
        else:
            i += 1
            j += 1
    return diffs + (len(a) - i) + (len(b) - j) <= 1


@router.get("/search")
async def search(q: str, user: dict = Depends(require_user), limit: int = 20):
    q = (q or "").strip()
    if not q:
        return {"results": [], "fallback": False}
    region = (user.get("country") or "GB").upper()
    local = _local_search(q, limit)
    local = apply_user_filters(local, user)
    if local:
        return {"results": local, "fallback": False}
    try:
        tmdb_results = await tmdb_client.search_titles(q, region=region, limit=limit)
        tmdb_results = apply_user_filters(tmdb_results or [], user)
        if tmdb_results:
            return {"results": tmdb_results, "fallback": False}
    except Exception as e:
        logger.warning(f"TMDB search failed: {e}")
    fallback = sorted(get_catalog(), key=lambda m: m.get("rating", 0), reverse=True)
    fallback = apply_user_filters(fallback, user)[:limit]
    return {"results": fallback, "fallback": True}


@router.get("/search/suggest")
async def search_suggest(q: str, user: dict = Depends(require_user), limit: int = 6):
    """Lightweight autocomplete: returns up to N matching titles by prefix."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return {"suggestions": []}
    candidates = apply_user_filters(get_catalog(), user)
    out = []
    for m in candidates:
        title = (m.get("title") or "")
        if title.lower().startswith(q) or f" {q}" in title.lower():
            out.append({
                "id": m["id"], "title": title, "year": m.get("year"),
                "type": m.get("type"), "poster_url": m.get("poster_url"),
            })
            if len(out) >= limit:
                break
    return {"suggestions": out}


@router.get("/movies/{movie_id}/similar")
async def similar(movie_id: str, user: dict = Depends(require_user)):
    """Card-based 'More Like This'.

    Uses `card_similarity` (40% themes / 25% tone / 20% audience / 10% pacing /
    5% genre) instead of raw genre overlap. Falls back to TMDB similar API for
    titles outside the local catalog.
    """
    m = find_movie(movie_id)
    if not m:
        raise HTTPException(404, "Movie not found")
    target_card = m.get("card") or build_card(m)

    def score(c: dict) -> float:
        c_card = c.get("card") or build_card(c)
        return card_similarity(target_card, c_card)

    candidates = [c for c in get_catalog() if c["id"] != movie_id]
    candidates.sort(key=score, reverse=True)
    # Keep only items with non-trivial similarity (> 0.15)
    local_top = [c for c in candidates if score(c) >= 0.15][:12]

    if len(local_top) >= 8 or not m.get("tmdb_id"):
        return local_top

    # Augment with TMDB similar — classify on the fly
    region = (user.get("country") or "GB").upper()
    try:
        tmdb_sim = await tmdb_client.fetch_similar(m["type"], m["tmdb_id"], region=region)
    except Exception:
        tmdb_sim = []
    seen_ids = {x["id"] for x in local_top}
    for t in tmdb_sim:
        if t["id"] not in seen_ids:
            if not t.get("card"):
                t["card"] = build_card(t)
            local_top.append(t)
            if len(local_top) >= 12:
                break
    return local_top
