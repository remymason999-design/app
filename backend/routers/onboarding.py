"""Onboarding router.

Exposes three endpoints used by the 4-step onboarding flow:

   GET  /onboarding/titles   -> up to 10 popular titles from selected genres (mix of
                               eras, and both movies + TV) for the "Rate these"
                               step. Excludes anything the user has already
                               touched or rated during onboarding.

  POST /onboarding/rate     -> records a like / dislike / skip for a title,
                               updates genre_weights + type_weights live, and
                               adds the movie to user.onboarding_rated so it
                               never reappears in Discover.

  POST /onboarding/complete -> marks onboarding_completed = true.
"""
import os
import random
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from routers.discovery import invalidate_discover_cache
from pydantic import BaseModel

from core import db, require_user, get_catalog, find_movie, clean_user, apply_user_filters, catalog_quality_gate
from content_cards import card_similarity, franchise_matches
from taste import onboarding_learning_inc, build_taste_profile

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

ONBOARD_WEIGHTS = {"like": 4.0, "dislike": -3.0, "skip": 0}
MIN_ONBOARDING_INTERACTIONS = 5
MAX_ONBOARDING_INTERACTIONS = 10


class RateIn(BaseModel):
    movie_id: str
    rating: Literal["like", "dislike", "skip"]


def _pick_diverse_titles(user: dict, n: int = MAX_ONBOARDING_INTERACTIONS, seen: set = None) -> list:
    """Pick n taste-check titles personalised to the user's filters + selected genres.

    Selected genres take turns choosing quality-ranked titles.  Roughly four
    out of five cards are selected-genre matches; the rest are controlled,
    quality-gated adjacent discovery rather than random fill.

    Strategy
    --------
    1. Apply all user filters (excluded_categories, subscriptions, content_type).
    2. Split pool into genre-matching / other.
    3. Pick from the genre pool in round-robin order without duplicates.
    4. Fill supply gaps from other pool (bucket cap 2).
    5. Top up from either pool if under-filled (small / narrow catalog).
    """
    seen = seen or set()
    selected_genres = set(user.get("genres") or [])

    catalog = [m for m in get_catalog() if m["id"] not in seen and m.get("poster_url")]
    catalog = apply_user_filters(catalog, user)

    # Onboarding hygiene — the first impression must be high-quality and on-brand:
    #   • drop junk / unreleased / unwatchable titles (same gate as Discover)
    #   • suppress Reality/Talk unless the user explicitly picked those genres
    # A thin deck is preferable to violating this quality gate: exhaustion is a
    # first-class completion escape, never a licence to show poor cards.
    _reality_selected = bool(selected_genres & {"Reality", "Talk"})
    _user_region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    _hygienic = [
        m for m in catalog
        if catalog_quality_gate(m, user_region=_user_region, user=user)
        and (_reality_selected or not (set(m.get("genres") or []) & {"Reality", "Talk"}))
    ]
    catalog = _hygienic

    if not catalog:
        return []

    # UK-first foreign handling: down-weight (never remove) non-English titles in
    # the quality sort so international titles earn an onboarding slot only when
    # they're genuinely popular/relevant. Pool stays intact. Only relevant when
    # international content is enabled (otherwise it's already filtered upstream).
    _show_intl = user.get("show_international", True)

    def _quality(m: dict) -> float:
        q = (m.get("popularity") or 0) * float(m.get("rating") or 7)
        if _show_intl and (m.get("original_language") or "en") != "en":
            q *= 0.6
        return q

    def _novelty_score(candidate: dict, pool: list, chosen: list) -> float:
        """Quality-first soft novelty: near-duplicates lose a later slot."""
        top_quality = max((_quality(item) for item in pool), default=1.0) or 1.0
        candidate_card = candidate.get("card") or {}
        penalty = 0.0
        for prior in chosen:
            prior_card = prior.get("card") or {}
            similarity = card_similarity(candidate_card, prior_card)
            same_franchise_cluster = bool(
                franchise_matches(
                    candidate_card.get("franchise"),
                    prior_card.get("franchise"),
                )
                and (
                    candidate_card.get("tone") == prior_card.get("tone")
                    or set(candidate_card.get("themes") or [])
                    & set(prior_card.get("themes") or [])
                )
            )
            penalty = max(
                penalty,
                0.45 * similarity + (0.15 if same_franchise_cluster else 0.0),
            )
        return _quality(candidate) / top_quality - penalty

    def _pick_with_diversity(pool: list, target: int,
                             preferred_genres: set, cap_per_bucket: int) -> list:
        """Greedily pick up to `target` titles with a per-(genre,type) bucket cap.

        Bucket key for genre-matching items is the first matching preferred
        genre so Horror always fills the Horror bucket regardless of genres[0].
        """
        buckets: dict = {}
        chosen: list = []
        remaining = list(pool)
        while remaining and len(chosen) < target:
            permitted: list[tuple[dict, tuple]] = []
            for m in remaining:
                m_genres = set(m.get("genres") or [])
                if preferred_genres:
                    matching = list(m_genres & preferred_genres)
                    bucket_g = sorted(matching)[0] if matching else (m.get("genres") or ["Other"])[0]
                else:
                    bucket_g = (m.get("genres") or ["Other"])[0]
                key = (bucket_g, m.get("type") or "movie")
                if buckets.get(key, 0) < cap_per_bucket:
                    permitted.append((m, key))
            if not permitted:
                break
            m, key = max(
                permitted,
                key=lambda pair: _novelty_score(pair[0], pool, chosen),
            )
            remaining.remove(m)
            buckets[key] = buckets.get(key, 0) + 1
            chosen.append(m)
        return chosen

    if selected_genres:
        # Split by whether the title has ANY selected genre
        genre_pool = [m for m in catalog if set(m.get("genres") or []) & selected_genres]
        other_pool = [m for m in catalog if not (set(m.get("genres") or []) & selected_genres)]

        genre_pool.sort(key=_quality, reverse=True)
        other_pool.sort(key=_quality, reverse=True)

        # Keep a compact controlled-discovery slice.  It is based on the same
        # curated adjacency graph Discover uses, then falls back to quality-only
        # titles only if the filtered catalogue cannot supply enough cards.
        from engine import ADJACENT_GENRES
        adjacent_genres = set().union(*(set(ADJACENT_GENRES.get(g, [])) for g in selected_genres))
        adjacent_pool = [
            m for m in other_pool if set(m.get("genres") or []) & adjacent_genres
        ]
        adjacent_pool.sort(key=_quality, reverse=True)
        discovery_target = min(max(1, round(n * 0.2)), len(adjacent_pool))
        target_genre = min(len(genre_pool), n - discovery_target)
        genre_chosen: list = []
        chosen_ids = set()
        while len(genre_chosen) < target_genre:
            added = False
            for genre in sorted(selected_genres):
                candidates = [
                    m for m in genre_pool
                    if m["id"] not in chosen_ids and genre in (m.get("genres") or [])
                ]
                candidate = max(
                    candidates,
                    key=lambda m: _novelty_score(m, genre_pool, genre_chosen),
                    default=None,
                )
                if candidate:
                    genre_chosen.append(candidate)
                    chosen_ids.add(candidate["id"])
                    added = True
                if len(genre_chosen) >= target_genre:
                    break
            if not added:
                break

        # Adjacent portion: diverse controlled discovery.  If it is exhausted,
        # use other high-quality titles only for the remaining necessary slots.
        other_chosen = (_pick_with_diversity(adjacent_pool, discovery_target,
                                            set(), cap_per_bucket=2)
                        if discovery_target else [])
        chosen = genre_chosen + other_chosen
    else:
        # No genre selection — quality-ranked with light (2-per-bucket) diversity
        catalog.sort(key=_quality, reverse=True)
        chosen = _pick_with_diversity(catalog, n, set(), cap_per_bucket=2)

    # Top up only from selected-genre or controlled-adjacent pools.  Never use
    # unrelated filler for a user who expressed genres; a short/exhausted deck
    # is handled explicitly by /onboarding/progress and /complete.
    if len(chosen) < n:
        chosen_ids = {c["id"] for c in chosen}
        if selected_genres:
            fallback = sorted(
                [m for m in catalog if (
                    set(m.get("genres") or []) & selected_genres
                    or set(m.get("genres") or []) & adjacent_genres
                )],
                key=_quality,
                reverse=True,
            )
        else:
            fallback = sorted(catalog, key=_quality, reverse=True)
        for m in fallback:
            if m["id"] in chosen_ids:
                continue
            chosen.append(m)
            if len(chosen) >= n:
                break

    random.shuffle(chosen)
    return chosen[:n]


def _eligible_onboarding_ids(user: dict) -> set[str]:
    """Broad quality/relevance eligibility, stable across deck reshuffles."""
    seen = set(
        (user.get("saved") or []) + (user.get("watched") or []) +
        (user.get("skipped") or [])
    )
    selected_genres = set(user.get("genres") or [])
    region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    pool = apply_user_filters(
        [m for m in get_catalog() if m["id"] not in seen and m.get("poster_url")],
        user,
    )
    pool = [
        m for m in pool
        if catalog_quality_gate(m, user_region=region, user=user)
        and (
            selected_genres & {"Reality", "Talk"}
            or not (set(m.get("genres") or []) & {"Reality", "Talk"})
        )
    ]
    if not selected_genres:
        return {movie["id"] for movie in pool}
    from engine import ADJACENT_GENRES
    adjacent = set().union(*(set(ADJACENT_GENRES.get(g, [])) for g in selected_genres))
    allowed_genres = selected_genres | adjacent
    return {
        movie["id"] for movie in pool
        if set(movie.get("genres") or []) & allowed_genres
    }


@router.get("/titles")
async def onboarding_titles(user: dict = Depends(require_user), limit: int = Query(default=MAX_ONBOARDING_INTERACTIONS, ge=1, le=20)):
    seen = set(
        (user.get("saved") or []) + (user.get("watched") or []) + (user.get("skipped") or []) +
        (user.get("onboarding_rated") or [])
    )
    # Older native binaries request 18; cap the training deck at ten.
    remaining = max(0, MAX_ONBOARDING_INTERACTIONS - len(user.get("onboarding_rated") or []))
    picks = _pick_diverse_titles(user, n=min(limit, MAX_ONBOARDING_INTERACTIONS, remaining), seen=seen)
    return [
        {
            "id": m["id"],
            "title": m["title"],
            "type": m.get("type"),
            "year": m.get("year"),
            "overview": m.get("overview"),
            "poster_url": m.get("poster_url"),
            "backdrop_url": m.get("backdrop_url"),
            "rating": m.get("rating"),
            "genres": (m.get("genres") or [])[:3],
        }
        for m in picks
    ]


@router.get("/progress")
async def onboarding_progress(user: dict = Depends(require_user)):
    """Stable UI contract for the short taste-training deck."""
    interactions = len(user.get("onboarding_rated") or [])
    remaining = max(0, MAX_ONBOARDING_INTERACTIONS - interactions)
    # Exhaustion is a safe escape for tightly filtered/small catalogues.
    seen = set((user.get("saved") or []) + (user.get("watched") or []) +
               (user.get("skipped") or []) + (user.get("onboarding_rated") or []))
    exhausted = not _pick_diverse_titles(user, n=1, seen=seen)
    complete = bool(user.get("onboarding_completed"))
    return {
        "interactions": interactions,
        "minimum_interactions": MIN_ONBOARDING_INTERACTIONS,
        "maximum_interactions": MAX_ONBOARDING_INTERACTIONS,
        "remaining": remaining,
        "can_finish": complete or interactions >= MIN_ONBOARDING_INTERACTIONS or exhausted,
        "exhausted": exhausted,
        "is_complete": complete,
    }


@router.post("/rate")
async def onboarding_rate(payload: RateIn, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")
    uid = user["user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Idempotent: only update weights the first time a movie is rated.
    # If it's already in onboarding_rated, treat the call as a no-op for scoring.
    already = payload.movie_id in (user.get("onboarding_rated") or [])
    if user.get("onboarding_completed") and not already:
        raise HTTPException(400, "Onboarding is already complete")
    if not already and payload.movie_id not in _eligible_onboarding_ids(user):
        raise HTTPException(400, "Title is not eligible for the current onboarding deck")

    update: dict = {
        "$addToSet": {"onboarding_rated": payload.movie_id},
        "$set": {
            "onboarding_completed": False,
            "last_action_at": now_iso,
        },
    }
    # Skip intelligence (Task #23): an onboarding dislike is a deliberate
    # rejection — record it as a HARD skip so it is never reintro-eligible.
    if payload.rating == "dislike" and not already:
        update["$addToSet"]["hard_skips"] = payload.movie_id
    delta = ONBOARD_WEIGHTS.get(payload.rating, 0)
    if delta and not already:
        # Source-separated deliberate onboarding evidence.  Card display itself
        # never reaches this endpoint and therefore has no learning effect.
        inc = onboarding_learning_inc(movie, delta)
        if inc:
            update["$inc"] = inc
    result = await db.users.update_one(
        {
            "user_id": uid,
            "onboarding_completed": {"$ne": True},
            "onboarding_rated": {"$ne": payload.movie_id},
            "$expr": {
                "$lt": [
                    {"$size": {"$ifNull": ["$onboarding_rated", []]}},
                    MAX_ONBOARDING_INTERACTIONS,
                ]
            },
        },
        update,
    )
    if result.modified_count == 0:
        # A competing request may have filled the deck.  Re-read to preserve
        # idempotent retries while rejecting a different eleventh card.
        fresh_after_race = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
        if payload.movie_id not in (fresh_after_race.get("onboarding_rated") or []):
            if fresh_after_race.get("onboarding_completed"):
                raise HTTPException(400, "Onboarding is already complete")
            raise HTTPException(400, f"Onboarding deck is limited to {MAX_ONBOARDING_INTERACTIONS} cards")
        already = True
    else:
        already = False
    # Onboarding ratings seed feed weights — invalidate so first /discover after
    # rating reflects the new signal immediately.
    invalidate_discover_cache(uid)

    if not already:
        await db.user_actions.insert_one({
            "user_id": uid,
            "movie_id": payload.movie_id,
            "action": f"onboard_{payload.rating}",
            "created_at": now_iso,
        })

    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if fresh and not already:
        tp = build_taste_profile(fresh)
        await db.users.update_one({"user_id": uid}, {"$set": {"taste_profile": tp}})
        fresh["taste_profile"] = tp
    return {"ok": True, "user": clean_user(fresh)}


@router.post("/complete")
async def onboarding_complete(user: dict = Depends(require_user)):
    uid = user["user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Completion is deliberately idempotent: retrying a completed request must
    # not reset its completion timestamp or alter any affinity.
    if user.get("onboarding_completed"):
        return clean_user(user)

    interactions = len(user.get("onboarding_rated") or [])
    if not user.get("onboarding_completed") and interactions < MIN_ONBOARDING_INTERACTIONS:
        seen = set((user.get("saved") or []) + (user.get("watched") or []) +
                   (user.get("skipped") or []) + (user.get("onboarding_rated") or []))
        if _pick_diverse_titles(user, n=1, seen=seen):
            raise HTTPException(400, f"Rate at least {MIN_ONBOARDING_INTERACTIONS} cards before finishing")

    # Seed initial genre_weights from the genres the user selected in step 1.
    # This ensures the very first Discover feed is personalised even before any
    # swipes happen. Only seeds genres that haven't been touched by onboard swipes yet.
    existing_gw = user.get("genre_weights") or {}
    selected_genres = user.get("genres") or []
    genre_seed: dict = {}
    for g in selected_genres:
        if (existing_gw.get(g) or 0) == 0:
            genre_seed[f"genre_weights.{g}"] = 1.0  # gentle cold-start seed

    update: dict = {
        "$set": {
            "onboarding_completed": True,
            "onboarding_completed_at": now_iso,
            **genre_seed,
        }
    }
    await db.users.update_one({"user_id": uid}, update)
    invalidate_discover_cache(uid)
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if fresh:
        tp = build_taste_profile(fresh)
        await db.users.update_one({"user_id": uid}, {"$set": {"taste_profile": tp}})
        fresh["taste_profile"] = tp
    return clean_user(fresh)
