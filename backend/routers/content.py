"""Content router: movies/{id}, /search, /search/suggest, similar."""
import asyncio
import os
import re
import time
from fastapi import APIRouter, Depends, HTTPException

from core import (
    db, require_user, get_catalog, find_movie, tmdb_client, logger,
    apply_user_filters,
)
from content_cards import build_card, card_similarity
from providers_util import (
    DEFAULT_REGION, resolve_region_providers, build_region_entry,
    needs_region_refresh,
)
from routers.discovery import invalidate_discover_cache


async def _track_search_signal(user_id: str, q: str, results: list) -> None:
    """Fire-and-forget: log search query and nudge genre weights if query
    clearly references a genre name (e.g. user types 'horror films')."""
    try:
        await db.users.update_one(
            {"user_id": user_id},
            {"$push": {"search_history": {"$each": [q], "$slice": -20, "$position": 0}}},
        )
        # search_history itself feeds build_feed's search_genre_boost — any
        # update to it must invalidate the cached feed, not just genre matches.
        invalidate_discover_cache(user_id)
        if not results:
            return
        # Collect genres from the top results
        result_genres: set[str] = set()
        for m in results[:8]:
            for g in (m.get("genres") or []):
                result_genres.add(g)
        q_lower = q.lower()
        matched = [g for g in result_genres if q_lower in g.lower() or g.lower() in q_lower]
        if matched:
            inc = {f"genre_weights.{g}": 0.05 for g in matched[:3]}
            await db.users.update_one({"user_id": user_id}, {"$inc": inc})
    except Exception as e:
        logger.debug(f"Search signal tracking failed: {e}")

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

    # On-demand trailer: if still missing but we have a TMDB id, fetch and cache
    if not out.get("trailer_youtube_id") and out.get("tmdb_id") and out.get("type"):
        try:
            key = await tmdb_client.fetch_trailer(out["type"], int(out["tmdb_id"]))
            if key:
                out["trailer_youtube_id"] = key
                await db.movies_cache.update_one(
                    {"id": movie_id}, {"$set": {"trailer_youtube_id": key}}
                )
        except Exception:
            pass

    # ── Region-aware provider resolution + on-demand fetch ────────────────────
    # Availability is region-specific, so we resolve providers for the *user's*
    # region (not whatever region the bulk job happened to enrich), and fetch
    # lazily when that region's data is missing or stale.
    region_code = (user.get("country") or DEFAULT_REGION).upper()
    out = await _hydrate_providers_for_region(out, movie_id, region_code)
    # ─────────────────────────────────────────────────────────────────────────

    # ── TV: season-level availability ─────────────────────────────────────────
    # TMDB exposes watch providers at the show level only; there is no per-season
    # provider feed.  Where a show streams, all of its seasons stream, so we
    # surface the show's resolved availability on each season and mark it as
    # inherited (never fabricated) so the UI can be honest about it.
    if out.get("type") == "tv" and isinstance(out.get("seasons"), list):
        for s in out["seasons"]:
            if isinstance(s, dict):
                s["available_on"]        = out.get("available_on") or []
                s["rent_on"]             = out.get("rent_on") or []
                s["buy_on"]              = out.get("buy_on") or []
                s["availability_inherited"] = True
                s["provider_region"]     = out.get("provider_region")
    # ─────────────────────────────────────────────────────────────────────────

    progress = (user.get("progress") or {}).get(movie_id)
    if progress:
        out["progress"] = progress
    return out


async def _hydrate_providers_for_region(
    out: dict, movie_id: str, region_code: str, force: bool = False
) -> dict:
    """Resolve (and lazily fetch) provider availability for `region_code`.

    Mutates and returns `out` with region-correct `available_on/rent_on/buy_on`
    plus trust metadata: `provider_region`, `provider_confidence`,
    `providers_fetched_at`, `availability_region_matched`.

    Integrity rule: a live fetch only writes through when TMDB actually
    responded (`ok`).  A failed/rate-limited fetch leaves prior data untouched
    and never records a false "confirmed empty".
    """
    # Prefer the freshest copy of region-keyed data from the DB (in-memory
    # CATALOG only mirrors the default region's flat fields).
    db_doc = await db.movies_cache.find_one(
        {"id": movie_id},
        {"_id": 0, "providers_by_region": 1, "available_on": 1, "rent_on": 1,
         "buy_on": 1, "providers_fetched": 1, "providers_region": 1,
         "providers_fetched_at": 1, "providers_empty_confirmed": 1},
    )
    source = db_doc or out
    resolved = resolve_region_providers(source, region_code)

    should_fetch = (
        force or needs_region_refresh(source, region_code)
    ) and out.get("tmdb_id") and out.get("type")

    if should_fetch:
        try:
            providers = await tmdb_client.fetch_providers(
                out["type"], int(out["tmdb_id"]), region_code
            )
            if providers.get("ok"):
                entry = build_region_entry(
                    providers.get("flatrate", []),
                    providers.get("rent", []),
                    providers.get("buy", []),
                )
                set_fields = {f"providers_by_region.{region_code}": entry}
                if region_code == DEFAULT_REGION:
                    set_fields.update({
                        "available_on":              entry["available_on"],
                        "rent_on":                   entry["rent_on"],
                        "buy_on":                    entry["buy_on"],
                        "providers_fetched":         True,
                        "providers_fetched_at":      entry["fetched_at"],
                        "providers_region":          region_code,
                        "providers_empty_confirmed": entry["empty_confirmed"],
                        "provider_confidence":       entry["confidence"],
                    })
                await db.movies_cache.update_one({"id": movie_id}, {"$set": set_fields})
                cached = find_movie(movie_id)
                if cached is not None:
                    cached.setdefault("providers_by_region", {})[region_code] = entry
                    if region_code == DEFAULT_REGION:
                        cached["available_on"]              = entry["available_on"]
                        cached["rent_on"]                   = entry["rent_on"]
                        cached["buy_on"]                    = entry["buy_on"]
                        cached["providers_fetched"]         = True
                        cached["providers_empty_confirmed"] = entry["empty_confirmed"]
                resolved = {
                    **entry, "region": region_code,
                    "region_matched": True, "stale": False,
                }
                logger.info(
                    f"On-demand providers for {movie_id} ({region_code}): "
                    f"flatrate={entry['available_on']} "
                    f"empty_confirmed={entry['empty_confirmed']}"
                )
            else:
                logger.info(
                    f"On-demand provider fetch for {movie_id} ({region_code}) "
                    f"returned no response — not recording as empty"
                )
        except Exception as exc:
            logger.debug(f"On-demand provider fetch failed for {movie_id}: {exc}")

    out["available_on"]                = resolved["available_on"]
    out["rent_on"]                     = resolved["rent_on"]
    out["buy_on"]                      = resolved["buy_on"]
    out["provider_region"]             = resolved["region"]
    out["provider_confidence"]         = resolved["confidence"]
    out["providers_fetched_at"]        = resolved["fetched_at"]
    out["providers_empty_confirmed"]   = resolved["empty_confirmed"]
    out["availability_region_matched"] = resolved["region_matched"]
    out["providers_fetched"]           = resolved["region_matched"]
    return out


@router.post("/movies/{movie_id}/refresh-providers")
async def refresh_providers(movie_id: str, user: dict = Depends(require_user)):
    """Force an on-demand provider refresh for the user's region.

    Used when availability looks missing/stale/wrong for a region.  Always does a
    live TMDB fetch (force=True); integrity rules in the hydrate helper ensure a
    failed fetch never overwrites good data or records a false empty.
    """
    m = find_movie(movie_id) or await db.movies_cache.find_one({"id": movie_id}, {"_id": 0})
    if not m:
        raise HTTPException(404, "Movie not found")
    if not (m.get("tmdb_id") and m.get("type")):
        raise HTTPException(400, "Title has no TMDB id to refresh from")
    region_code = (user.get("country") or DEFAULT_REGION).upper()
    out = await _hydrate_providers_for_region(dict(m), movie_id, region_code, force=True)
    return {
        "id":                          movie_id,
        "provider_region":             out.get("provider_region"),
        "available_on":                out.get("available_on") or [],
        "rent_on":                     out.get("rent_on") or [],
        "buy_on":                      out.get("buy_on") or [],
        "provider_confidence":         out.get("provider_confidence"),
        "providers_fetched_at":        out.get("providers_fetched_at"),
        "providers_empty_confirmed":   out.get("providers_empty_confirmed"),
        "availability_region_matched": out.get("availability_region_matched"),
    }


def _close_match(a: str, b: str) -> bool:
    """1-edit-distance check for short tokens — used only as fuzzy fallback
    when the regex search returns zero results."""
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


def _provider_ids_matching(q_lower: str) -> list:
    """Return service ids whose name matches the query exactly OR by substring.

    Used ONLY for the explicit `?provider=` query-param fallback and for
    backwards-compat callers. The /search query parser uses
    `_extract_providers_from_query` instead, which is strict and word-bounded
    so common-word tokens like "max" (Mad Max) or "prime" (Prime Suspect) are
    never mistaken for provider names.
    """
    from movies_seed import STREAMING_SERVICES
    out = []
    for s in STREAMING_SERVICES:
        sid = (s.get("id") or "").lower()
        name = (s.get("name") or "").lower()
        if q_lower in name or q_lower in sid:
            out.append(s["id"])
    return out


# ── Strict provider phrase / token aliases (used by the /search parser) ─────
# Phrases are checked first, longest-first, so "hbo max" matches before any
# attempt to interpret "max" on its own. Single tokens are restricted to
# unambiguous provider names; ambiguous words like "max", "prime", "paramount",
# or "apple" are deliberately NOT included to avoid false-positive provider
# constraints on title / person queries (Mad Max, Prime Suspect, etc.).
_PROVIDER_PHRASE_ALIASES: list[tuple[str, str]] = [
    ("hbo max",        "hbo_max"),
    ("disney plus",    "disney_plus"),
    ("prime video",    "prime_video"),
    ("amazon prime",   "prime_video"),
    ("amazon video",   "prime_video"),
    ("apple tv plus",  "apple_tv"),
    ("apple tv+",      "apple_tv"),
    ("apple tv",       "apple_tv"),
    ("paramount plus", "paramount"),
    ("paramount+",     "paramount"),
]

_PROVIDER_SINGLE_ALIASES: dict[str, str] = {
    "netflix":      "netflix",
    "hulu":         "hulu",
    "peacock":      "peacock",
    "disney+":      "disney_plus",
}


def _extract_providers_from_query(q_lower: str) -> tuple[list[str], str]:
    """Strip provider phrases from a lowercased query and return (ids, leftover).

    Detects only EXACT word-bounded phrase matches; substring matches that
    would catch "max" in "Mad Max" or "prime" in "Prime Suspect" are
    intentionally excluded.
    """
    ids: list[str] = []
    padded = f" {q_lower} "
    for phrase, pid in _PROVIDER_PHRASE_ALIASES:
        needle = f" {phrase} "
        if needle in padded:
            if pid not in ids:
                ids.append(pid)
            padded = padded.replace(needle, " ")
    return ids, padded.strip()


def _apply_region_availability(m: dict, region: str, subs: set) -> None:
    """Project region-correct provider lists + label onto a search result.

    Search is region-aware: a title streaming on Netflix GB but rent-only in the
    US must be labelled differently for each user.  We resolve the providers for
    the caller's region and overwrite the flat fields on the result with that
    region's data before labelling.
    """
    resolved = resolve_region_providers(m, region)
    m["available_on"]                = resolved["available_on"]
    m["rent_on"]                     = resolved["rent_on"]
    m["buy_on"]                      = resolved["buy_on"]
    m["provider_region"]             = resolved["region"]
    m["provider_confidence"]         = resolved["confidence"]
    m["availability_region_matched"] = resolved["region_matched"]
    avail = set(resolved["available_on"])
    m["on_subscription"] = bool(subs and (avail & subs))
    if not resolved["region_matched"]:
        m["availability_label"] = "unknown_region"
    elif subs and (avail & subs):
        m["availability_label"] = "included"
    elif avail:
        m["availability_label"] = "elsewhere"
    elif resolved["rent_on"] or resolved["buy_on"]:
        m["availability_label"] = "rent_or_buy"
    else:
        m["availability_label"] = "unavailable"


@router.get("/search")
async def search(
    q: str,
    user: dict = Depends(require_user),
    limit: int = 20,
    offset: int = 0,
    only_my_subscriptions: bool = False,
    hide_unavailable: bool = False,
    content_type: str | None = None,   # "movie" | "tv" | None
    provider: str | None = None,       # service id, e.g. "netflix"
    genre: str | None = None,          # case-insensitive single genre
    year: int | None = None,           # exact year filter
    debug: bool = False,
):
    """Universal catalogue search (IMDb / JustWatch style).

    Queries the full `movies_cache` collection across:
      title, overview, genres, keywords, tags, year (4-digit), provider id+name.

    Returns EVERY matching title regardless of:
      - the user's subscriptions
      - rent/buy availability
      - excluded categories/genres (those are Discover preferences, not
        catalogue exclusions)
      - already-seen state

    Each result is labelled (included / elsewhere / rent_or_buy / unavailable)
    so the UI can show availability without hiding anything.

    Optional caller-supplied filters narrow the result set on demand:
      only_my_subscriptions  — only titles on at least one of the user's subs
      hide_unavailable       — drop titles with no provider/rent/buy info
      content_type           — "movie" or "tv"
      provider               — single service id (e.g. "netflix")
      genre                  — single genre name (case-insensitive)
      year                   — exact release year
    """
    t0 = time.time()
    q = (q or "").strip()
    if not q:
        return {"results": [], "fallback": False, "has_more": False}
    region = (user.get("country") or "GB").upper()
    subs = set(user.get("subscriptions") or [])
    ql = q.lower()

    # ── Multi-signal query parser ────────────────────────────────────────────
    # The query is split into whitespace tokens. Each token is classified:
    #
    #   • provider token  → "netflix", "disney+", "hbo"   (consumes the token,
    #                       adds a provider AND-clause)
    #   • year token      → 4 digits 1900-2100             (year AND-clause)
    #   • decade token    → "90s", "1990s", "2000s"        (year-range AND)
    #   • content token   → everything else                (AND'd over an OR
    #                       across all searchable fields)
    #
    # This lets mixed-intent searches like "Netflix horror" or "90s comedy"
    # resolve into a proper compound query instead of a single regex looking
    # for the literal phrase in any one field. Detected provider/year tokens
    # are removed from the content-token list so they don't double-filter.
    # Phase 1 — pull multi-word provider phrases out of the raw query so
    # "hbo max" / "prime video" / "apple tv" are detected before tokenisation
    # ever sees them. This is strict: only exact word-bounded phrases count.
    parsed_provider_ids, leftover_q = _extract_providers_from_query(ql)
    raw_tokens = [t for t in re.split(r"\s+", leftover_q) if t]
    content_tokens: list[str] = []
    parsed_years: list[int] = []
    parsed_decade_ranges: list[tuple[int, int]] = []

    DECADE_RX = re.compile(r"^(?:19|20)?(\d{1,2})s$")  # 90s, 1990s, 00s, 2000s
    for tok in raw_tokens:
        tl = tok.lower()
        # provider — single-token aliases ONLY (unambiguous names like
        # "netflix" / "hulu" / "peacock"). Ambiguous words like "max",
        # "prime", "paramount", "apple" are deliberately excluded so
        # queries like "Mad Max" or "Prime Suspect" don't get a
        # spurious provider AND-clause attached.
        single_pid = _PROVIDER_SINGLE_ALIASES.get(tl)
        if single_pid:
            if single_pid not in parsed_provider_ids:
                parsed_provider_ids.append(single_pid)
            continue
        # year
        if tl.isdigit() and len(tl) == 4:
            try:
                y = int(tl)
                if 1900 <= y <= 2100:
                    parsed_years.append(y)
                    continue
            except ValueError:
                pass
        # decade
        md = DECADE_RX.match(tl)
        if md:
            d = int(md.group(1))
            # "90s" → 1990s, "00s" → 2000s; full forms keep their century.
            if len(tl) <= 3:                       # "90s", "00s"
                base = 1900 + d * 10 if d >= 30 else 2000 + d * 10
            else:                                   # "1990s", "2000s"
                base = int(tl[:-1]) // 10 * 10
            if 1900 <= base <= 2100:
                parsed_decade_ranges.append((base, base + 9))
                continue
        content_tokens.append(tok)

    # If the whole query was provider/year tokens (e.g. just "Netflix"),
    # fall back to using the original query as a single content token so
    # there's still something to match against.
    if not content_tokens and not parsed_provider_ids and not parsed_years and not parsed_decade_ranges:
        content_tokens = [q]

    detected_types: list = []

    def _token_or(tok: str) -> dict:
        """OR-across-fields clause for a single content token."""
        rx = {"$regex": re.escape(tok), "$options": "i"}
        return {"$or": [
            {"title":          rx},
            {"overview":       rx},
            {"genres":         rx},
            {"keywords":       rx},
            {"tags":           rx},
            {"cast_names":     rx},
            {"director_names": rx},
            {"writer_names":   rx},
            {"studio_names":   rx},
            {"aliases":        rx},
            {"collections":    rx},
        ]}

    # Build the AND'd content-clause: every content token must hit at least
    # one searchable field. Single-token queries collapse to the bare $or
    # so the engine can still use individual field indexes effectively.
    token_clauses: list = [_token_or(t) for t in content_tokens]
    if token_clauses:
        detected_types.extend([
            "title", "overview", "genre", "keyword", "tag",
            "cast", "director", "studio", "alias", "collection",
        ])

    # Apply caller-supplied optional filters DIRECTLY on the Mongo query so
    # pagination stays accurate (no in-memory slicing) and results scale.
    extra_and: list = []
    if content_type in ("movie", "tv"):
        extra_and.append({"type": content_type})
    if year and 1900 <= int(year) <= 2100:
        extra_and.append({"year": int(year)})
    if provider:
        pid = provider.strip().lower()
        extra_and.append({"$or": [
            {"available_on": pid}, {"rent_on": pid}, {"buy_on": pid},
        ]})
    if genre:
        # Case-insensitive exact-genre match (genres stored Title-cased)
        extra_and.append({"genres": {"$regex": f"^{re.escape(genre)}$", "$options": "i"}})
    if only_my_subscriptions and subs:
        extra_and.append({"available_on": {"$in": list(subs)}})
    if hide_unavailable:
        # "available somewhere" = on a streaming service, rent, or buy list
        extra_and.append({"$or": [
            {"available_on": {"$exists": True, "$ne": []}},
            {"rent_on":      {"$exists": True, "$ne": []}},
            {"buy_on":       {"$exists": True, "$ne": []}},
        ]})

    # Parser-derived AND filters (provider tokens, year tokens, decades).
    if parsed_provider_ids:
        extra_and.append({"$or": [
            {"available_on": {"$in": parsed_provider_ids}},
            {"rent_on":      {"$in": parsed_provider_ids}},
            {"buy_on":       {"$in": parsed_provider_ids}},
        ]})
        detected_types.append("provider")
    if parsed_years:
        extra_and.append({"year": {"$in": parsed_years}})
        detected_types.append("year")
    for lo, hi in parsed_decade_ranges:
        extra_and.append({"year": {"$gte": lo, "$lte": hi}})
        detected_types.append("decade")

    # Assemble the final Mongo query. token_clauses live inside the same
    # top-level $and so EVERY content token must match.
    all_and = token_clauses + extra_and
    if not all_and:
        mongo_q = {}
    elif len(all_and) == 1:
        mongo_q = all_and[0]
    else:
        mongo_q = {"$and": all_and}

    # Backwards-compat for the debug payload below
    matching_providers = parsed_provider_ids

    db_t0 = time.time()
    try:
        total = await db.movies_cache.count_documents(mongo_q)
    except Exception:
        total = 0
    cursor = (
        db.movies_cache.find(mongo_q, {"_id": 0})
        .sort([("popularity", -1), ("rating", -1)])
        .skip(offset)
        .limit(limit + 1)
    )
    items = await cursor.to_list(length=limit + 1)
    db_ms = int((time.time() - db_t0) * 1000)
    has_more = len(items) > limit
    items = items[:limit]

    # Lightweight typo tolerance: only when no exact-substring matches exist
    # AND the query is reasonably long. Cheap whole-token edit-distance scan
    # over the in-memory CATALOG keeps misspellings like
    # "intersteller" → Interstellar working without a Mongo regex hit.
    typo_used = False
    # Fuzzy fallback is only safe when the query is a single content blob
    # with no extra constraints — otherwise it can return results that
    # don't satisfy the parsed provider/year/decade or caller filters.
    _no_extra_constraints = not extra_and
    if not items and offset == 0 and len(q) >= 4 and _no_extra_constraints:
        # Build the haystack tokens from title, cast, director, studio so a
        # misspelled person/studio name still finds matches (e.g. "Hollnd").
        # Multi-word queries are matched token-by-token; we accept a movie if
        # EVERY query token has a 1-edit match against some token of any of
        # the considered fields.
        q_tokens = [t for t in ql.split() if len(t) >= 3]
        if not q_tokens:
            q_tokens = [ql]

        def _doc_tokens(m: dict) -> set:
            tokens: set = set()
            for v in ([m.get("title")] + (m.get("cast_names") or []) + (m.get("director_names") or []) + (m.get("writer_names") or []) + (m.get("studio_names") or [])):
                if not v:
                    continue
                for w in str(v).lower().split():
                    if len(w) >= 3:
                        tokens.add(w)
            return tokens

        fuzzy = []
        for m in get_catalog():
            doc_toks = _doc_tokens(m)
            if not doc_toks:
                continue
            ok = True
            for qt in q_tokens:
                hit = False
                for dt in doc_toks:
                    if abs(len(dt) - len(qt)) <= 1 and _close_match(qt, dt):
                        hit = True
                        break
                if not hit:
                    ok = False
                    break
            if ok:
                fuzzy.append(m)
        if fuzzy:
            fuzzy.sort(key=lambda m: m.get("popularity", 0), reverse=True)
            total = len(fuzzy)
            items = fuzzy[offset: offset + limit]
            # Recompute has_more against the fuzzy result set so pagination
            # works correctly when the fuzzy fallback supplies the items.
            has_more = (offset + limit) < total
            typo_used = True
            detected_types.append("fuzzy_match")

    # NO Discover-pool filtering — search is a universal catalogue lookup.
    # Every result keeps its place; the label below tells the UI what the
    # availability is so the user can see (not hide) the full match set.
    for m in items:
        _apply_region_availability(m, region, subs)

    # If the local DB returned NOTHING, fall back to TMDB and cache results.
    fallback = False
    if not items and offset == 0 and not extra_and:
        try:
            tmdb_results = await tmdb_client.search_titles(q, region=region, limit=limit)
            tmdb_results = tmdb_results or []
            if tmdb_results:
                from pymongo import UpdateOne
                from content_cards import build_card
                ops = []
                for m in tmdb_results:
                    if not m.get("card"):
                        m["card"] = build_card(m)
                    ops.append(UpdateOne({"id": m["id"]}, {"$set": m}, upsert=True))
                try:
                    await db.movies_cache.bulk_write(ops, ordered=False)
                except Exception:
                    pass
                for m in tmdb_results:
                    _apply_region_availability(m, region, subs)
                items = tmdb_results
                fallback = True
        except Exception as e:
            logger.warning(f"TMDB search fallback failed: {e}")

    if offset == 0:
        asyncio.create_task(_track_search_signal(user["user_id"], q, items))

    payload = {
        "results": items,
        "fallback": fallback,
        "has_more": has_more,
        # `total` is the number of matching catalogue entries (before
        # pagination).  When the TMDB fallback kicks in it reflects what we
        # just fetched from TMDB.  Used by the UI for "X results" copy.
        "total": (len(items) if fallback else total),
    }
    if debug:
        active_filters = []
        if only_my_subscriptions: active_filters.append("only_my_subscriptions")
        if hide_unavailable:      active_filters.append("hide_unavailable")
        if content_type:          active_filters.append(f"content_type={content_type}")
        if provider:              active_filters.append(f"provider={provider}")
        if genre:                 active_filters.append(f"genre={genre}")
        if year:                  active_filters.append(f"year={year}")
        payload["debug"] = {
            "collection": "movies_cache",
            "total_matches": total,
            "returned": len(items),
            "offset": offset,
            "limit": limit,
            "query": q,
            "query_types_detected": detected_types,
            "provider_matches": matching_providers,
            "active_optional_filters": active_filters or ["none"],
            "fallback_to_tmdb": fallback,
            "fuzzy_typo_fallback": typo_used,
            "db_query_ms": db_ms,
            "total_ms": int((time.time() - t0) * 1000),
        }
    return payload


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

    Uses ONLY card_similarity (40% themes / 25% tone / 20% audience /
    10% pacing / 5% genre). Falls back to TMDB ONLY when local pool is too
    sparse (<8 results above similarity floor) — and TMDB results are also
    classified into cards before re-scoring (no genre-overlap fallback).
    """
    m = find_movie(movie_id)
    if not m:
        raise HTTPException(404, "Movie not found")
    target_card = m.get("card") or build_card(m)

    # Apply user filters before scoring — never recommend filtered content
    candidates = [c for c in get_catalog() if c["id"] != movie_id]
    candidates = apply_user_filters(candidates, user)

    scored = []
    for c in candidates:
        c_card = c.get("card") or build_card(c)
        sim = card_similarity(target_card, c_card)
        if sim >= 0.15:
            scored.append((sim, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    local_top = [c for _, c in scored[:12]]

    if len(local_top) >= 8 or not m.get("tmdb_id"):
        return local_top

    # Augment with TMDB similar — classify each into a card and re-score
    region = (user.get("country") or "GB").upper()
    try:
        tmdb_sim = await tmdb_client.fetch_similar(m["type"], m["tmdb_id"], region=region)
    except Exception:
        tmdb_sim = []
    tmdb_sim = apply_user_filters(tmdb_sim or [], user)
    seen_ids = {x["id"] for x in local_top}
    aug = []
    for t in tmdb_sim:
        if t["id"] in seen_ids:
            continue
        if not t.get("card"):
            t["card"] = build_card(t)
        sim = card_similarity(target_card, t["card"])
        if sim >= 0.10:  # slightly lower floor for augmentation pool
            aug.append((sim, t))
    aug.sort(key=lambda x: x[0], reverse=True)
    for _, t in aug:
        local_top.append(t)
        if len(local_top) >= 12:
            break
    return local_top
