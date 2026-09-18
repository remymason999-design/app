"""Joint recommendation engine for the "For you both" compare surface.

This module owns ``_shared_recommendations`` (Feature 2). It builds a joint
scoring model over the loaded catalog for a PAIR of users. Unlike the main
Discover feed (which mutates NO candidate pools and is soft-re-rank only), the
compare surface is its own dedicated surface and MAY apply hard exclusions —
the rules below are scoped to this surface only.

Design
──────
For each candidate title we compute an individual predicted score for *each*
user with the existing per-user hybrid scorer (``engine._hybrid_score``), so the
score reflects each user's own taste INCLUDING their negative weights. We then
combine them:

    joint_score = min(score_a, score_b)
                + mutual_genre_bonus
                + mutual_tone_bonus
                + shared_provider_bonus
                + community_quality_bonus
                - dislike_conflict_penalty
                - hard_skip_penalty
                - already_seen_penalty

``min(a, b)`` is the fairness core — a title only ranks high if it works for the
WEAKER-matching user, not just the enthusiast. Bonuses/penalties then reward
mutual overlap and punish conflict.

Hard exclusions (this surface only) — see ``_excluded_for_pair``.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import List, Optional

from core import (
    get_catalog, catalog_quality_gate, _hidden_by_uk_default,
    _is_family_kids,
)
from providers_util import resolve_region_providers
from engine import _hybrid_score, _maturity, _neg_maturity
from progress import progress_fingerprint


# ── Joint-score tuning weights ────────────────────────────────────────────
MUTUAL_GENRE_BONUS      = 1.2   # per shared, mutually-liked genre (capped)
MUTUAL_GENRE_CAP        = 3.6
MUTUAL_TONE_BONUS       = 1.0   # both lean toward the title's tone
SHARED_PROVIDER_BONUS   = 1.5   # available on a service BOTH subscribe to
COMMUNITY_QUALITY_BONUS = 1.0   # high community/critical quality (rating+votes)
DISLIKE_CONFLICT_PENALTY = 4.0  # one user's taste is clearly negative on it
HARD_SKIP_PENALTY       = 6.0   # (defensive — hard-skips are also excluded)
ALREADY_SEEN_PENALTY    = 3.0   # (defensive — seen titles are also excluded)

# ── Performance guards (Feature 2) ─────────────────────────────────────────
# Cap the number of candidates that reach the (expensive) double hybrid-score
# pass. We cheaply pre-filter (exclusions first) and keep only the best
# rating/community-quality candidates — the compare surface is a "top picks"
# list, so the tail of low-quality inventory can never win anyway.
CANDIDATE_PRECAP = 400

# Small in-process TTL cache for compare recommendations. The compare endpoint
# is polled every few seconds by the client; recomputing a full joint ranking on
# every poll is wasteful. Keyed by the (sorted user pair + both users' action
# counts) so it invalidates automatically the moment either user acts.
_CACHE_TTL_SEC = 600          # 10 minutes
_CACHE_MAX_ENTRIES = 200
_REC_CACHE: "dict[tuple, tuple[float, list]]" = {}


def _region_of(user: dict) -> str:
    return (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()


def _learned_top_genres(user: dict, n: int = 6) -> set:
    gw = user.get("genre_weights") or {}
    pos = [(g, w) for g, w in gw.items() if isinstance(w, (int, float)) and w > 0]
    pos.sort(key=lambda kv: kv[1], reverse=True)
    return {g for g, _ in pos[:n]}


def _user_score(movie: dict, user: dict, current_year: int) -> float:
    """Per-user predicted score via the shared hybrid scorer.

    Uses sensible context: per-user positive/negative maturity, that user's
    learned top genres, an empty collaborative set (compare is synchronous and
    collab requires a DB round-trip we deliberately skip here), and no
    session-fatigue / search boosts. Reflects the user's OWN taste including
    negative genre/tone/language/decade weights.
    """
    return _hybrid_score(
        movie, user,
        maturity=_maturity(user),
        neg_maturity=_neg_maturity(user),
        collab_set=set(),
        learned_top_genres=_learned_top_genres(user),
        current_year=current_year,
    )


def _mutually_liked_genres(movie: dict, a: dict, b: dict) -> list:
    """Genres on the title that BOTH users lean positive toward.

    A user "leans positive" on a genre if it's in their onboarding picks OR
    their learned genre weight is > 0. A negative learned weight disqualifies it.
    """
    mg = movie.get("genres") or []
    a_gw = a.get("genre_weights") or {}
    b_gw = b.get("genre_weights") or {}
    a_pref = set(a.get("genres") or [])
    b_pref = set(b.get("genres") or [])

    def _likes(u_gw, u_pref, g) -> bool:
        w = u_gw.get(g, 0)
        if isinstance(w, (int, float)) and w < 0:
            return False
        return (g in u_pref) or (isinstance(w, (int, float)) and w > 0)

    return [g for g in mg if _likes(a_gw, a_pref, g) and _likes(b_gw, b_pref, g)]


def _mutual_tone(movie: dict, a: dict, b: dict) -> Optional[str]:
    """Return the title's tone if BOTH users have a positive weight for it."""
    tone = (movie.get("card") or {}).get("tone")
    if not tone or tone == "neutral":
        return None
    aw = (a.get("tone_weights") or {}).get(tone, 0)
    bw = (b.get("tone_weights") or {}).get(tone, 0)
    if isinstance(aw, (int, float)) and isinstance(bw, (int, float)) and aw > 0 and bw > 0:
        return tone
    return None


def _has_dislike_conflict(movie: dict, a: dict, b: dict) -> bool:
    """True if EITHER user's learned weights are clearly negative on the title's
    dominant signals (a genre or the tone), i.e. it would fight their taste."""
    mg = set(movie.get("genres") or [])
    tone = (movie.get("card") or {}).get("tone")

    def _conflict(u: dict) -> bool:
        gw = u.get("genre_weights") or {}
        for g in mg:
            w = gw.get(g, 0)
            if isinstance(w, (int, float)) and w <= -3.0:
                return True
        if tone:
            tw = (u.get("tone_weights") or {}).get(tone, 0)
            if isinstance(tw, (int, float)) and tw <= -2.5:
                return True
        return False

    return _conflict(a) or _conflict(b)


def _watched_disliked(user: dict, mid: str) -> bool:
    """True if the user watched+disliked this title (new watched_feedback map
    sentiment, or legacy watched_disliked list)."""
    fb = (user.get("watched_feedback") or {}).get(mid)
    if isinstance(fb, dict) and fb.get("sentiment") == "disliked":
        return True
    if mid in (user.get("watched_disliked") or []):
        return True
    return False


def _can_watch(movie: dict, user: dict) -> bool:
    """True if the title is on a service the user has selected, resolved for the
    user's region (flatrate/known services). If the user has no subscriptions
    set we can't prove availability against a service list, so treat as watchable
    (benefit of the doubt — the quality gate already required *some* provider)."""
    subs = set(user.get("subscriptions") or [])
    if not subs:
        return True
    available = set(resolve_region_providers(movie, _region_of(user))["available_on"])
    return bool(available & subs)


def _violates_content_settings(movie: dict, user: dict) -> bool:
    """Explicit content settings / anime-Asian-drama opt-outs / language prefs /
    excluded genres / excluded categories — reuse the default-pool helpers."""
    # anime + Asian-language drama opt-out (unless show_anime_asian)
    if _hidden_by_uk_default(movie, user):
        return True
    excluded_cats = set(user.get("excluded_categories") or [])
    if ("family" in excluded_cats or "kids" in excluded_cats) and _is_family_kids(movie):
        return True
    excluded_genres = set(user.get("excluded_genres") or [])
    if excluded_genres & set(movie.get("genres") or []):
        return True
    # English-only mode
    if not user.get("show_international", True):
        if (movie.get("original_language") or "en") != "en":
            return True
    # content type
    ct = user.get("content_type")
    if ct and ct != "both" and movie.get("type") != ct:
        return True
    # auto-blocked languages/decades
    if (movie.get("original_language") or "en") in set(user.get("auto_blocked_languages") or []):
        return True
    _y = movie.get("year") or 0
    if _y:
        _dec = f"{(_y // 10) * 10}s"
        if _dec in set(user.get("auto_blocked_decades") or []):
            return True
    return False


def _excluded_for_pair(movie: dict, a: dict, b: dict, *, seen: set) -> Optional[str]:
    """Return an exclusion reason code if the title must NOT appear on the
    "For you both" surface, else None. HARD exclusions (this surface only).
    """
    mid = movie["id"]
    a_region = _region_of(a)

    # Already on either watchlist / already interacted (belongs in Both/You/Friend).
    if mid in seen:
        return "already_seen"

    # Either user hard-skipped it.
    if mid in set(a.get("hard_skips") or []) or mid in set(b.get("hard_skips") or []):
        return "hard_skip"

    # Either user watched+disliked it.
    if _watched_disliked(a, mid) or _watched_disliked(b, mid):
        return "watched_disliked"

    # Either user hid it.
    if mid in set(a.get("hidden") or []) or mid in set(b.get("hidden") or []):
        return "hidden"

    # Low-quality fallback inventory — gate on EXPLICIT-bad values only (the
    # gate itself gives missing/None fields the benefit of the doubt).
    if not catalog_quality_gate(movie, user_region=a_region, user=a):
        return "quality_gate"

    # Explicit content settings / opt-outs / language prefs for either user.
    if _violates_content_settings(movie, a) or _violates_content_settings(movie, b):
        return "content_settings"

    # NEITHER user can watch it on their selected services.
    if not _can_watch(movie, a) and not _can_watch(movie, b):
        return "no_shared_availability"

    return None


# Human-readable genre joins for reason strings.
def _join_two(items: list) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _build_reason(components: dict) -> str:
    """Machine-generate a reason string grounded in the actual score components.

    Never returns a generic reason unless nothing specific is supported.
    """
    shared_genres = components.get("shared_genres") or []
    shared_provider = components.get("shared_provider")
    mutual_tone = components.get("mutual_tone")
    community = components.get("community_quality")

    if len(shared_genres) >= 2:
        return f"Matches both of your {_join_two(shared_genres[:2]).lower()} taste"
    if len(shared_genres) == 1:
        base = f"Matches both of your {shared_genres[0].lower()} taste"
        if shared_provider:
            return base + " — and it's on a service you both use"
        return base
    if mutual_tone:
        return f"You both gravitate toward {mutual_tone} stories"
    if shared_provider:
        return "Available on a service you both use"
    if community:
        return "Popular with people who share both your tastes"
    # No specific mutual signal — be honest rather than overclaiming, especially
    # when one user's taste conflicts with the title.
    if components.get("dislike_conflict"):
        return "A compromise pick — not a perfect match for either of you"
    return "A solid middle-ground pick for the two of you"


def _action_count(user: dict) -> int:
    """Cheap change-detection fingerprint for a user's interaction state.

    Any save/watch/skip/hide/hard-skip/feedback mutation changes this number, so
    it's a safe cache key: when it changes we recompute. Prefer updated_at when
    present (also bumped on any write) for extra safety.
    """
    n = (
        len(user.get("saved") or []) + len(user.get("watched") or []) +
        len(user.get("skipped") or []) + len(user.get("hidden") or []) +
        len(user.get("hard_skips") or []) + len(user.get("watched_feedback") or {})
    )
    return n


def _cache_key(me: dict, them: dict, limit: int) -> tuple:
    a_id, b_id = me.get("user_id"), them.get("user_id")
    # Sort the pair so (A,B) and (B,A) share nothing — the result is per-viewer
    # (seen sets / regions differ), so keep both ids in viewer order but include
    # both action counts + updated_at so any change on either side invalidates.
    return (
        a_id, b_id, limit,
        _action_count(me), _action_count(them),
        me.get("updated_at"), them.get("updated_at"),
        progress_fingerprint(me), progress_fingerprint(them),
    )


def _cache_get(key: tuple):
    entry = _REC_CACHE.get(key)
    if not entry:
        return None
    ts, value = entry
    if (time.monotonic() - ts) > _CACHE_TTL_SEC:
        _REC_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value: list) -> None:
    # Bounded LRU-ish: drop the oldest entries when over capacity.
    if len(_REC_CACHE) >= _CACHE_MAX_ENTRIES:
        for old_key in sorted(_REC_CACHE, key=lambda k: _REC_CACHE[k][0])[:max(1, _CACHE_MAX_ENTRIES // 10)]:
            _REC_CACHE.pop(old_key, None)
    _REC_CACHE[key] = (time.monotonic(), value)


def _precap_candidates(me: dict, them: dict, *, seen: set, counts: dict) -> list:
    """Cheaply pre-filter to at most CANDIDATE_PRECAP candidates BEFORE the
    expensive hybrid-score pass. Runs hard exclusions first, then keeps the
    best by rating + a community-quality tiebreak (vote_count)."""
    survivors: list = []
    for m in get_catalog():
        counts["candidates"] += 1
        reason_code = _excluded_for_pair(m, me, them, seen=seen)
        if reason_code:
            counts[reason_code] = counts.get(reason_code, 0) + 1
            continue
        survivors.append(m)
    if len(survivors) > CANDIDATE_PRECAP:
        survivors.sort(
            key=lambda m: (float(m.get("rating") or 0), int(m.get("vote_count") or 0)),
            reverse=True,
        )
        counts["precapped"] = len(survivors) - CANDIDATE_PRECAP
        survivors = survivors[:CANDIDATE_PRECAP]
    return survivors


def _shared_recommendations(me: dict, them: dict, limit: int = 8, *,
                            debug_counts: "dict | None" = None,
                            use_cache: bool = True) -> List[dict]:
    """Joint "For you both" recommendations for a pair of users.

    Returns titles NEITHER user has on their watchlist (or otherwise interacted
    with), ranked by the joint scoring model, each with a grounded ``reason`` and
    per-item debug fields (score_a, score_b, joint_score, shared_genres).
    """
    # ── In-process TTL cache (invalidated by either user's action count) ─────
    cache_key = _cache_key(me, them, limit) if use_cache else None
    if cache_key is not None:
        cached = _cache_get(cache_key)
        if cached is not None:
            if debug_counts is not None:
                debug_counts.update({"cache_hit": True})
            return cached

    seen = set(
        (me.get("saved") or []) + (me.get("watched") or []) + (me.get("skipped") or []) +
        (them.get("saved") or []) + (them.get("watched") or []) + (them.get("skipped") or [])
    )
    shared_subs = set(me.get("subscriptions") or []) & set(them.get("subscriptions") or [])
    current_year = datetime.now(timezone.utc).year

    counts = {
        "candidates": 0, "already_seen": 0, "hard_skip": 0, "watched_disliked": 0,
        "hidden": 0, "quality_gate": 0, "content_settings": 0,
        "no_shared_availability": 0, "precapped": 0, "scored": 0, "cache_hit": False,
    }

    # Cheap pre-cap: run exclusions + rating/quality sort BEFORE hybrid scoring
    # so the expensive double-score pass touches at most CANDIDATE_PRECAP titles.
    candidates = _precap_candidates(me, them, seen=seen, counts=counts)

    scored: list[tuple[float, dict]] = []
    for m in candidates:
        score_a = _user_score(m, me, current_year)
        score_b = _user_score(m, them, current_year)

        shared_genres = _mutually_liked_genres(m, me, them)
        mutual_genre_bonus = min(MUTUAL_GENRE_CAP, MUTUAL_GENRE_BONUS * len(shared_genres))

        mutual_tone = _mutual_tone(m, me, them)
        mutual_tone_bonus = MUTUAL_TONE_BONUS if mutual_tone else 0.0

        on_shared = bool(shared_subs and (set(m.get("available_on") or []) & shared_subs))
        shared_provider_bonus = SHARED_PROVIDER_BONUS if on_shared else 0.0

        rating = float(m.get("rating") or 0)
        votes = int(m.get("vote_count") or 0)
        high_quality = rating >= 7.5 and votes >= 1000
        community_quality_bonus = COMMUNITY_QUALITY_BONUS if high_quality else 0.0

        dislike_penalty = DISLIKE_CONFLICT_PENALTY if _has_dislike_conflict(m, me, them) else 0.0

        joint = (
            min(score_a, score_b)
            + mutual_genre_bonus
            + mutual_tone_bonus
            + shared_provider_bonus
            + community_quality_bonus
            - dislike_penalty
        )

        components = {
            "shared_genres": shared_genres,
            "shared_provider": on_shared,
            "mutual_tone": mutual_tone,
            "community_quality": high_quality,
            "dislike_conflict": dislike_penalty > 0,
        }
        reason = _build_reason(components)

        counts["scored"] += 1
        scored.append((joint, {
            "id": m["id"], "title": m["title"], "type": m.get("type"),
            "poster_url": m.get("poster_url"), "rating": m.get("rating"),
            "genres": (m.get("genres") or [])[:3],
            "available_on": m.get("available_on") or [],
            "reason": reason,
            "shared_genres": shared_genres,
            "score_a": round(score_a, 3),
            "score_b": round(score_b, 3),
            "joint_score": round(joint, 3),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    result = [item for _s, item in scored[:limit]]
    if cache_key is not None:
        _cache_put(cache_key, result)
    if debug_counts is not None:
        debug_counts.update(counts)
    return result
