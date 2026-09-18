"""User router: preferences, actions, watchlist, watched, services, genres, progress."""
import asyncio
from datetime import date, datetime, timezone
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from core import (
    db, require_user, clean_user, public_user,
    PreferencesIn, ActionIn, EngageIn, ProgressIn, EpisodeProgressIn,
    movies_by_ids, find_movie, ACTION_WEIGHTS,
    STREAMING_SERVICES, GENRES,
    movie_matches, catalog_quality_gate, _age_tier, _classic_exception_ok,
)
from progress import (episode_key, normalize_progress, watched_episode_count,
                      inferred_episode_count, completion_metadata)
from tmdb import hydrate_tv_seasons
from engine import ADJACENT_GENRES
from taste import taste_learning_inc, build_taste_profile
from routers.insights import invalidate_insights_cache
from routers.discovery import invalidate_discover_cache

router = APIRouter(tags=["user"])


async def _hydrate_progress_movie(movie: dict | None) -> dict | None:
    """Lazily attach episode metadata without mutating the catalog record."""
    if not movie or movie.get("type") != "tv" or not movie.get("tmdb_id"):
        return movie
    hydrated = dict(movie)
    hydrated["seasons"] = await hydrate_tv_seasons(
        int(movie["tmdb_id"]), movie.get("seasons"))
    return hydrated


# ── Watched-sentiment learning deltas (Feature 1) ─────────────────────────
# When a user explicitly rates a title they WATCHED, the sentiment overrides the
# legacy save/skip inference. Deltas mirror the ACTION_WEIGHTS scale so the same
# learning code paths (genre/tone/pacing/theme/language/decade + taste_learning_inc)
# push similar content up (loved/liked) or DOWN (disliked).
WATCHED_SENTIMENT_DELTAS = {
    "loved":    2.5,
    "liked":    1.5,
    "neutral":  0.3,
    "disliked": -2.0,
}
# "Haven't finished" (completed=False, no sentiment): a tiny, strictly-positive
# nudge — the user engaged enough to start it, but this is NOT a full like and
# must never be negative.
UNFINISHED_DELTA = 0.1


class ActionInExt(ActionIn):
    """ActionIn + optional watched-sentiment fields (Feature 1).

    Subclasses the core model so the frontend contract (movie_id/action/
    impression_id) is unchanged while adding opt-in sentiment fields.
    """
    watched_sentiment: Optional[Literal["loved", "liked", "neutral", "disliked"]] = None
    completed: bool = True


class WatchedFeedbackIn(BaseModel):
    """Change a watched-title rating later (POST /user/watched-feedback)."""
    movie_id: str
    watched_sentiment: Literal["loved", "liked", "neutral", "disliked"]
    completed: bool = True


def _taste_inc_for_delta(movie: dict, user: dict, delta: float) -> dict:
    """Build the full Mongo ``$inc`` fragment for applying a signed learning
    ``delta`` to a movie's taste signals.

    This is the single source of truth for how a swipe/sentiment nudges the
    user's learned weights: genre, type, tone, pacing, theme, language, decade
    and the soft ``taste_learning_inc`` signals (cast/director/writer via
    ``person_key`` sanitization, runtime/popularity/quality).

    Returning the fragment lets callers PERSIST the exact applied deltas so a
    later reversal (unwatched / re-rating) can apply the exact negative — Mongo
    ``$inc`` is linear, so ``$inc`` by ``-x`` perfectly reverses ``$inc`` by ``x``.

    NOTE: language/decade *compounding* (present in the live-swipe path) is
    intentionally NOT applied here — compounding makes the effective delta
    non-linear and therefore not exactly reversible. Sentiment learning uses a
    plain linear delta so REWIND is exact. The exposure counters
    (lang_neg/lang_pos/decade_neg/decade_pos) are also omitted here to keep the
    reversal purely about scoring weights.
    """
    inc: dict = {}
    if not delta:
        return inc
    genres = movie.get("genres") or []
    genre_count = max(1, len(genres))
    delta_per_genre = round(delta / genre_count, 4)
    for g in genres:
        inc[f"genre_weights.{g}"] = delta_per_genre
    inc[f"type_weights.{movie.get('type', 'movie')}"] = round(delta * 0.6, 4)

    card = movie.get("card") or {}
    tone = card.get("tone")
    if tone and tone != "neutral":
        inc[f"tone_weights.{tone}"] = round(delta * 0.45, 4)
    pacing = card.get("pacing")
    if pacing and pacing != "medium":
        inc[f"pacing_weights.{pacing}"] = round(delta * 0.30, 4)
    for theme in (card.get("verified_themes") or card.get("themes") or [])[:3]:
        inc[f"theme_weights.{theme}"] = round(delta * 0.25, 4)

    lang = movie.get("original_language")
    if lang:
        inc[f"language_weights.{lang}"] = round(delta * 1.0, 4)
    _year = movie.get("year")
    if _year:
        _decade = f"{(_year // 10) * 10}s"
        inc[f"decade_weights.{_decade}"] = round(delta * 0.8, 4)

    # Soft taste signals (cast/director/writer via person_key, runtime, etc.)
    for k, v in taste_learning_inc(movie, delta).items():
        inc[k] = round(inc.get(k, 0) + v, 4)
    return inc


def _negate_inc(inc: dict) -> dict:
    """Return the exact inverse of an ``$inc`` fragment (for REWIND)."""
    return {k: round(-v, 4) for k, v in (inc or {}).items()}


def _post_onboarding_count_update(user_id: str, movie_id: str) -> tuple[dict, dict]:
    """Atomic, once-per-title counter update for onboarding-source decay.

    A title can move save → watched or be removed and re-saved; none of those
    retries should accelerate the decay.  Legacy profiles have no separate
    onboarding source map and therefore cannot match this predicate.
    """
    return (
        {
            "user_id": user_id,
            "onboarding_completed": True,
            "onboarding_genre_weights": {"$exists": True, "$ne": {}},
            "post_onboarding_counted_ids": {"$ne": movie_id},
        },
        {
            "$addToSet": {"post_onboarding_counted_ids": movie_id},
            "$inc": {"post_onboarding_interactions": 1},
        },
    )


@router.get("/services")
async def services():
    return STREAMING_SERVICES


@router.get("/genres")
async def list_genres():
    return GENRES


_VALID_SERVICE_IDS = {s["id"] for s in STREAMING_SERVICES}
_VALID_GENRES = set(GENRES)
_VALID_CATEGORIES = {"family", "anime", "bollywood"}


def _derive_effective_monthly_cost(plan: dict, billing_cycle: str, included: bool) -> float:
    """Derive a SERVER-AUTHORITATIVE effective_monthly_cost from a DB plan doc.

    `plan` is a live document from the streaming_plans collection.

    Rules:
      • included_with_other_provider → 0 (bundled at no extra cost)
      • free / licence_required plan → 0
      • annual billing (user's chosen billing_cycle == "annual", or the plan is
        itself annual-only) → annual_price / 12 (fall back to monthly_price when
        the plan has no annual_price)
      • otherwise → the plan's monthly_price
    Never trusts any client-supplied cost.
    """
    if included:
        return 0.0
    plan_billing = plan.get("billing_type")
    if plan_billing in ("free", "licence_required"):
        return 0.0
    if billing_cycle == "annual" or plan_billing == "annual":
        annual = plan.get("annual_price")
        if annual is not None:
            return round(float(annual) / 12.0, 2)
    return round(float(plan.get("monthly_price") or 0), 2)


async def _normalize_subscription_plans(raw: dict) -> dict:
    """Validate + normalize the per-service subscription_plans map.

    Server-authoritative pricing. For each entry:
      • Drop unknown service ids.
      • plan_id MUST exist in the LIVE streaming_plans collection AND belong to
        the same service_id — otherwise the entry is dropped (untrusted).
      • effective_monthly_cost is IGNORED from the client unless custom_price is
        true (an explicit user-entered price). When custom, it is clamped to
        0..100 and rounded to 2dp. Otherwise it is derived server-side from the
        DB plan doc (annual → annual_price/12; free/licence → 0; included → 0).
      • Only a fixed whitelist of fields is ever stored.
    """
    if not isinstance(raw, dict):
        return {}

    # Resolve all referenced plan_ids in one DB round-trip.
    requested_plan_ids = [
        (entry or {}).get("plan_id")
        for entry in raw.values()
        if isinstance(entry, dict) and (entry or {}).get("plan_id")
    ]
    plans_by_id: dict = {}
    if requested_plan_ids:
        docs = await db.streaming_plans.find(
            {"id": {"$in": requested_plan_ids}}, {"_id": 0}
        ).to_list(length=2000)
        plans_by_id = {d["id"]: d for d in docs}

    out: dict = {}
    for service_id, entry in raw.items():
        if service_id not in _VALID_SERVICE_IDS or not isinstance(entry, dict):
            continue

        plan_id = entry.get("plan_id")
        plan = plans_by_id.get(plan_id) if plan_id else None
        # plan_id must exist AND belong to this service — else drop the entry.
        if not plan or plan.get("service_id") != service_id:
            continue

        billing_cycle = entry.get("billing_cycle")
        if billing_cycle not in ("monthly", "annual"):
            billing_cycle = "monthly"
        custom_price = bool(entry.get("custom_price"))
        included = bool(entry.get("included_with_other_provider"))

        if custom_price and not included:
            # Explicit user-entered price — trust it, but clamp + round.
            try:
                cost = round(float(entry.get("effective_monthly_cost") or 0), 2)
            except (TypeError, ValueError):
                cost = 0.0
            cost = max(0.0, min(100.0, cost))
        else:
            # Always derive server-side; never trust the client value.
            cost = _derive_effective_monthly_cost(plan, billing_cycle, included)

        # Whitelist stored fields — drop anything else the client sent.
        clean = {
            "plan_id": plan_id,
            "billing_cycle": billing_cycle,
            "effective_monthly_cost": cost,
            "included_with_other_provider": included,
            "custom_price": custom_price,
        }
        promo_ends = entry.get("promo_ends")
        if isinstance(promo_ends, str) and promo_ends.strip():
            clean["promo_ends"] = promo_ends.strip()

        out[service_id] = clean
    return out


@router.put("/user/preferences")
async def set_prefs(payload: PreferencesIn, user: dict = Depends(require_user)):
    update = {}
    # Fresh registrations historically omit this flag. Persist their pending
    # state on first preferences write so restart migration cannot mistake them
    # for an older account. Completion transitions remain endpoint-gated below.
    if "onboarding_completed" not in user:
        update["onboarding_completed"] = False
    if payload.services is not None:
        # Drop unknown service IDs so a malformed/poisoned client can't store
        # arbitrary strings that would break downstream provider lookups.
        update["subscriptions"] = [s for s in payload.services if s in _VALID_SERVICE_IDS]
    if payload.genres is not None:
        update["genres"] = [g for g in payload.genres if g in _VALID_GENRES]
    if payload.moods is not None:
        update["moods"] = payload.moods
    if payload.excluded_categories is not None:
        update["excluded_categories"] = [c for c in payload.excluded_categories if c in _VALID_CATEGORIES]
    if payload.excluded_genres is not None:
        update["excluded_genres"] = [g for g in payload.excluded_genres if g in _VALID_GENRES]
    if payload.content_type is not None:
        update["content_type"] = payload.content_type
    if payload.country is not None:
        update["country"] = payload.country.upper()[:2]
    if payload.age is not None:
        update["age"] = max(1, min(120, payload.age))
    if payload.onboarding_completed is not None:
        # Completion has a minimum-interaction/exhaustion gate in the dedicated
        # onboarding endpoint. Preferences must never become a bypass (nor may
        # a completed user be accidentally returned to onboarding).
        if bool(payload.onboarding_completed) != bool(user.get("onboarding_completed")):
            raise HTTPException(
                400,
                "Onboarding completion is controlled by /onboarding/complete",
            )
    if payload.dob is not None:
        update["dob"] = payload.dob
    if payload.gender is not None:
        update["gender"] = payload.gender
    if payload.show_international is not None:
        update["show_international"] = bool(payload.show_international)
    if payload.show_anime_asian is not None:
        update["show_anime_asian"] = bool(payload.show_anime_asian)
    if payload.year_range is not None:
        update["year_range"] = payload.year_range
    if payload.include_other_services is not None:
        update["include_other_services"] = bool(payload.include_other_services)
    if payload.include_rent_buy is not None:
        update["include_rent_buy"] = bool(payload.include_rent_buy)
    if payload.subscription_plans is not None:
        update["subscription_plans"] = await _normalize_subscription_plans(payload.subscription_plans)
    if payload.tutorial_completed_at is not None:
        update["tutorial_completed_at"] = payload.tutorial_completed_at
    if update:
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
        # Any preference change (subs, country, genres, toggles, etc.) invalidates
        # the cached feed so the user immediately sees re-ranked recommendations.
        invalidate_discover_cache(user["user_id"])
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return public_user(fresh)


@router.post("/user/action")
async def user_action(payload: ActionInExt, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if not movie:
        # TMDB trending/upcoming movies may not be in the in-memory catalog yet;
        # fall back to the persistent cache so swipe actions always get recorded.
        movie = await db.movies_cache.find_one({"id": payload.movie_id}, {"_id": 0})
    if not movie:
        raise HTTPException(404, "Movie not found")
    field_map = {"save": "saved", "skip": "skipped", "watched": "watched"}
    uid = user["user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    if payload.action == "unsave":
        # Also decrement the unseen-watchlist badge counter (floor 0) — a
        # rewound save should not leave a phantom badge count behind.
        _before = await db.users.find_one_and_update(
            {"user_id": uid},
            {"$pull": {"saved": payload.movie_id}},
            projection={"_id": 0, "saved": 1, "watchlist_unseen": 1},
            return_document=ReturnDocument.BEFORE,
        ) or {}
        if payload.movie_id in (_before.get("saved") or []) and int(_before.get("watchlist_unseen") or 0) > 0:
            await db.users.update_one({"user_id": uid}, {"$inc": {"watchlist_unseen": -1}})
    elif payload.action == "unskip":
        await db.users.update_one({"user_id": uid}, {"$pull": {"skipped": payload.movie_id}})
    elif payload.action == "unwatched":
        # REWIND: reverse any sentiment learning that was applied when this
        # title was watched-with-sentiment, and drop the watched_feedback entry.
        # Concurrency-safe: atomically CLAIM the feedback entry ($unset with
        # return_document=BEFORE) and read the prior applied_inc from the
        # pre-image, then apply the exact negative in a single $inc. Only the
        # claimer sees a non-empty pre-image, so a concurrent duplicate unwatched
        # cannot double-reverse.
        _fb_key = f"watched_feedback.{payload.movie_id}"
        _claim = await db.users.find_one_and_update(
            {"user_id": uid},
            {"$pull": {"watched": payload.movie_id},
             "$unset": {_fb_key: ""}},
            projection={"_id": 0, _fb_key: 1},
            return_document=ReturnDocument.BEFORE,
        ) or {}
        rec = (_claim.get("watched_feedback") or {}).get(payload.movie_id)
        if rec and isinstance(rec, dict) and rec.get("applied_inc"):
            rev = _negate_inc(rec["applied_inc"])
            if rev:
                await db.users.update_one({"user_id": uid}, {"$inc": rev})
        invalidate_insights_cache(uid)
    else:
        field = field_map[payload.action]
        # ── Atomic action-semantics resolution (Task #7) ──────────────────────
        # Marking something "watched" carries different meaning depending on
        # what the user previously said about it:
        #   watched + previously saved   → "I loved it enough to actually watch"
        #                                  → strongest positive signal
        #   watched + previously skipped → "I gave it a chance and confirmed no"
        #                                  → strongest negative signal
        #   watched alone                → "I've seen this already, move on"
        #                                  → weak/neutral signal (mainly removes
        #                                    from feed)
        # We use find_one_and_update with ReturnDocument.BEFORE so the
        # pre-mutation state is observed atomically with the write — no
        # TOCTOU window between snapshot and mutation.
        before = await db.users.find_one_and_update(
            {"user_id": uid},
            {"$addToSet": {field: payload.movie_id},
             "$pull": {f: payload.movie_id for f in ["saved", "skipped", "watched"] if f != field},
             "$set": {"last_action_at": now_iso}},
            projection={"_id": 0, "saved": 1, "skipped": 1, "watched": 1},
            return_document=ReturnDocument.BEFORE,
        ) or {}

        # Count a completed-onboarding user's genuine title once, atomically.
        # The predicate prevents duplicate saves, undo/re-save cycles and
        # save→watched transitions from accelerating decay; it cannot match
        # legacy users lacking new source-separated evidence.
        _count_query, _count_update = _post_onboarding_count_update(uid, payload.movie_id)
        await db.users.update_one(_count_query, _count_update)

        # ── Watchlist notification badge (unseen count) ───────────────────
        # A NEW save (not already on the list) bumps the per-user unseen
        # counter; the badge is cleared explicitly when the user opens the
        # Watchlist page (POST /user/watchlist-seen) — never by a refresh.
        if payload.action == "save" and payload.movie_id not in (before.get("saved") or []):
            await db.users.update_one({"user_id": uid}, {"$inc": {"watchlist_unseen": 1}})

        # ── Watched-sentiment override (Feature 1) ────────────────────────────
        # When the client sends an explicit sentiment on a "watched" action we
        # use it instead of the save/skip inference. The sentiment delta is
        # applied through a LINEAR, reversible $inc fragment (see
        # _taste_inc_for_delta) and the exact fragment is persisted on the user
        # doc so unwatched / re-rating can reverse it precisely.
        sentiment_mode = False
        sentiment_delta = None
        sentiment_label = None
        if payload.action == "watched" and payload.watched_sentiment:
            sentiment_mode = True
            sentiment_label = payload.watched_sentiment
            sentiment_delta = WATCHED_SENTIMENT_DELTAS[payload.watched_sentiment]
        elif payload.action == "watched" and not payload.completed:
            # "Haven't finished" with no sentiment: tiny, strictly-positive nudge.
            sentiment_mode = True
            sentiment_label = None
            sentiment_delta = UNFINISHED_DELTA

        if payload.action == "watched":
            if payload.movie_id in (before.get("saved") or []):
                effective_action = "watched_liked"
            elif payload.movie_id in (before.get("skipped") or []):
                effective_action = "watched_disliked"
            else:
                effective_action = "watched"
        else:
            effective_action = payload.action

        if sentiment_mode:
            # ── Sentiment learning path (reversible + concurrency-safe) ──────
            delta = sentiment_delta
            effective_action = f"watched_sentiment:{sentiment_label or 'unfinished'}"
            applied_inc = _taste_inc_for_delta(movie, user, delta)
            # Atomically CLAIM any prior feedback entry: $unset the map key and
            # read the pre-image so concurrent re-rates each see the latest
            # committed record (no double-apply / missed reversal). We then apply
            # (reverse_prior + new_delta) as ONE combined $inc plus a $set of the
            # new record in a single update — the claim is the only race point.
            _fb_key = f"watched_feedback.{payload.movie_id}"
            _claim = await db.users.find_one_and_update(
                {"user_id": uid},
                {"$unset": {_fb_key: ""}},
                projection={"_id": 0, _fb_key: 1},
                return_document=ReturnDocument.BEFORE,
            ) or {}
            _prev = (_claim.get("watched_feedback") or {}).get(payload.movie_id)
            combined = dict(applied_inc)
            if _prev and isinstance(_prev, dict) and _prev.get("applied_inc"):
                for k, v in _negate_inc(_prev["applied_inc"]).items():
                    combined[k] = round(combined.get(k, 0) + v, 4)
            _new_record = {
                "sentiment": sentiment_label,
                "completed": bool(payload.completed),
                "delta": delta,
                "applied_inc": applied_inc,
                "at": now_iso,
            }
            _upd: dict = {"$set": {_fb_key: _new_record}}
            if combined:
                _upd["$inc"] = combined
            await db.users.update_one({"user_id": uid}, _upd)
        delta = sentiment_delta if sentiment_mode else ACTION_WEIGHTS.get(effective_action, 0)
        if delta and not sentiment_mode:
            genres = movie.get("genres") or []
            genre_count = max(1, len(genres))
            delta_per_genre = round(delta / genre_count, 4)
            inc = {f"genre_weights.{g}": delta_per_genre for g in genres}
            inc[f"type_weights.{movie.get('type', 'movie')}"] = round(delta * 0.6, 4)

            # ── Behavioral depth: learn tone, pacing, theme preferences ──────
            # Every swipe signals not just genre interest but *how* the user
            # wants to feel. These weights feed directly into the hybrid scorer.
            card = movie.get("card") or {}
            tone = card.get("tone")
            if tone and tone != "neutral":          # neutral is too generic to learn
                inc[f"tone_weights.{tone}"] = round(delta * 0.45, 4)
            pacing = card.get("pacing")
            if pacing and pacing != "medium":       # medium too common to be signal
                inc[f"pacing_weights.{pacing}"] = round(delta * 0.30, 4)
            # Top 3 themes only — prevents noise from low-signal inferred themes
            for theme in (card.get("verified_themes") or card.get("themes") or [])[:3]:
                inc[f"theme_weights.{theme}"] = round(delta * 0.25, 4)

            # ── Language preference learning ───────────────────────────────────
            # Soft signal for the hybrid scorer.  Compounding accelerates the
            # suppression of a language the user has already shown dislike for.
            # NOTE: these signed weights drive *scoring* only — the hard
            # blocklist below is rate-based, not weight-threshold based.
            lang = movie.get("original_language")
            _lw_now = (user.get("language_weights") or {})
            if lang:
                _lw_existing = _lw_now.get(lang, 0)
                if delta < 0 and -8.0 < _lw_existing < -1.5:
                    _lang_compound = 1.35
                elif delta < 0 and _lw_existing <= -8.0:
                    _lang_compound = 0.5   # near ceiling — slow further accumulation
                else:
                    _lang_compound = 1.0
                inc[f"language_weights.{lang}"] = round(delta * 1.0 * _lang_compound, 4)
                # Exposure counters — numerator/denominator for the rate-based
                # hard blocklist.  One per swipe, split positive vs negative.
                if delta < 0:
                    inc[f"lang_neg.{lang}"] = 1
                elif delta > 0:
                    inc[f"lang_pos.{lang}"] = 1

            # ── Decade preference learning ─────────────────────────────────────
            _year = movie.get("year")
            _dw_now = (user.get("decade_weights") or {})
            _decade = None
            if _year:
                _decade = f"{(_year // 10) * 10}s"
                _dw_existing = _dw_now.get(_decade, 0)
                if delta < 0 and -6.0 < _dw_existing < -1.0:
                    _decade_compound = 1.25
                elif delta < 0 and _dw_existing <= -6.0:
                    _decade_compound = 0.5
                else:
                    _decade_compound = 1.0
                inc[f"decade_weights.{_decade}"] = round(delta * 0.8 * _decade_compound, 4)
                if delta < 0:
                    inc[f"decade_neg.{_decade}"] = 1
                elif delta > 0:
                    inc[f"decade_pos.{_decade}"] = 1

            # ── Soft taste signals (Task #23): cast/runtime/popularity/quality ──
            # Scoring-only nudges — never filter the pool.
            inc.update(taste_learning_inc(movie, delta))

            if inc:
                await db.users.update_one({"user_id": uid}, {"$inc": inc})

            # ── Auto-blocklist management (rate + dominance based) ─────────────
            # A skip is the default swipe-left action, so raw skip *volume* is a
            # terrible block signal: in an English-dominant catalogue a normal
            # user skips mostly English, modern titles and would otherwise
            # auto-block their own primary language and decade — collapsing the
            # feed to almost nothing.  Instead, hard-block a language/decade only
            # when it is a genuine, singled-out aversion:
            #   • the user demonstrably engages positively somewhere
            #     (≥ MIN_TOTAL_POS positive swipes overall — save/watched/liked),
            #   • this category has a real sample of rejections (≥ MIN_NEG) with
            #     ZERO positives, and
            #   • it is NOT the user's dominant (most-seen) category — the
            #     dominant language/decade can never be auto-blocked.
            # Categories that no longer meet the bar are pulled (self-healing,
            # which also clears bad blocks created by the old volume-based rule).
            MIN_NEG = 12
            MIN_TOTAL_POS = 3

            def _merged(field: str) -> dict:
                base = dict(user.get(field) or {})
                prefix = field + "."
                for k, v in inc.items():
                    if k.startswith(prefix):
                        key = k[len(prefix):]
                        base[key] = base.get(key, 0) + v
                return base

            _lang_neg = _merged("lang_neg")
            _lang_pos = _merged("lang_pos")
            _dec_neg  = _merged("decade_neg")
            _dec_pos  = _merged("decade_pos")
            _total_lang_pos = sum(_lang_pos.values())
            _total_dec_pos  = sum(_dec_pos.values())

            def _dominant(neg: dict, pos: dict):
                keys = set(neg) | set(pos)
                if not keys:
                    return None
                return max(keys, key=lambda k: neg.get(k, 0) + pos.get(k, 0))

            _dom_lang   = _dominant(_lang_neg, _lang_pos)
            _dom_decade = _dominant(_dec_neg, _dec_pos)

            def _should_block(key, neg, pos, total_pos, dominant) -> bool:
                return (
                    key is not None
                    and key != dominant
                    and total_pos >= MIN_TOTAL_POS
                    and neg.get(key, 0) >= MIN_NEG
                    and pos.get(key, 0) == 0
                )

            _auto_add: dict  = {}
            _auto_pull: dict = {}
            _blocked_langs   = set(user.get("auto_blocked_languages") or [])
            _blocked_decades = set(user.get("auto_blocked_decades") or [])

            if lang and _should_block(lang, _lang_neg, _lang_pos, _total_lang_pos, _dom_lang) \
                    and lang not in _blocked_langs:
                _auto_add["auto_blocked_languages"] = lang
            for _bl in _blocked_langs:
                if not _should_block(_bl, _lang_neg, _lang_pos, _total_lang_pos, _dom_lang):
                    _auto_pull.setdefault("auto_blocked_languages", []).append(_bl)

            if _decade and _should_block(_decade, _dec_neg, _dec_pos, _total_dec_pos, _dom_decade) \
                    and _decade not in _blocked_decades:
                _auto_add["auto_blocked_decades"] = _decade
            for _bd in _blocked_decades:
                if not _should_block(_bd, _dec_neg, _dec_pos, _total_dec_pos, _dom_decade):
                    _auto_pull.setdefault("auto_blocked_decades", []).append(_bd)

            if _auto_add:
                await db.users.update_one({"user_id": uid}, {"$addToSet": _auto_add})
            if _auto_pull:
                _pull_doc = {k: {"$in": v} for k, v in _auto_pull.items()}
                await db.users.update_one({"user_id": uid}, {"$pull": _pull_doc})
        # ── Skip intelligence (Task #23 Step 8): classify hard vs soft ────────
        # A HARD skip is a deliberate, repeated rejection — the user skipped this
        # exact title before (it was already in `skipped`), or they previously
        # confirmed dislike by watching-then-disliking it.  Onboarding dislikes
        # are recorded as hard skips at onboarding time.  Hard skips never become
        # reintro-eligible (engine._eligible_skip_reintros).  A first-time skip
        # is SOFT — "not right now" — and may be reintroduced after the cooldown.
        skip_type = None
        if payload.action == "skip":
            repeated = (
                payload.movie_id in (before.get("skipped") or [])
                or payload.movie_id in (before.get("watched") or [])
            )
            skip_type = "hard" if repeated else "soft"
            if skip_type == "hard":
                await db.users.update_one(
                    {"user_id": uid}, {"$addToSet": {"hard_skips": payload.movie_id}}
                )
        # Audit trail for analytics + repetition control
        _log_row = {
            "user_id": uid, "movie_id": payload.movie_id, "action": payload.action,
            "created_at": now_iso,
        }
        if skip_type:
            _log_row["skip_type"] = skip_type
        # Persist watched-sentiment audit fields (Feature 1).
        if payload.action == "watched":
            _log_row["completed"] = bool(payload.completed)
            if payload.watched_sentiment:
                _log_row["watched_sentiment"] = payload.watched_sentiment
            if sentiment_mode:
                # Store enough to reverse: effective delta + the applied fragment.
                _log_row["sentiment_delta"] = sentiment_delta
                _log_row["applied_inc"] = applied_inc
        if payload.impression_id:
            _log_row["impression_id"] = payload.impression_id
        await db.user_actions.insert_one(_log_row)
        # ── Trigger incremental community-metric refresh (Task #38) ───────────
        # Fire-and-forget: does not block the swipe response.
        from global_learning import schedule_update_title_metrics
        schedule_update_title_metrics(payload.movie_id)
        if payload.action == "watched":
            invalidate_insights_cache(uid)

        # ── Exploration weight: adjust based on reactions to variety cards ───
        # Determine if this movie was a core/adjacent/wildcard card by comparing
        # its genres to the user's selected genres and the adjacent genre map.
        onboard_genres = set(user.get("genres") or [])
        if onboard_genres and payload.action in ("save", "watched", "skip"):
            movie_genres = set(movie.get("genres") or [])
            adjacent: set = set()
            for g in onboard_genres:
                adjacent |= set(ADJACENT_GENRES.get(g, []))
            adjacent -= onboard_genres
            if movie_genres & onboard_genres:
                slot_type = "core"
            elif movie_genres & adjacent:
                slot_type = "adjacent"
            else:
                slot_type = "wildcard"
            if slot_type in ("adjacent", "wildcard"):
                # Saves/watched_liked → user likes variety → widen exploration slowly
                # Skips/watched_disliked → user prefers core → narrow exploration
                # Plain watched (neutral) does not move the dial.
                #
                # Step sizes are intentionally small: skipping a variety card
                # often means "not in the mood right now", not "I hate variety".
                # Equilibrium analysis: at 30% save rate on variety:
                #   net = 0.30 × (+0.020) − 0.70 × (−0.008) = +0.006 − 0.0056 ≈ 0
                # This makes a neutral user (30% save) stay near 0.5 long-term,
                # skip-heavy (5%) drifts to floor, save-heavy (60%) drifts to cap.
                _sent = sentiment_label if sentiment_mode else None
                if effective_action in ("save", "watched_liked") or _sent in ("loved", "liked"):
                    step = 0.020
                elif effective_action in ("skip", "watched_disliked") or _sent == "disliked":
                    step = -0.008
                else:
                    step = 0.0   # plain/neutral watched — no exploration signal
            else:
                step = 0.0
            if step:
                current_w = float(user.get("exploration_weight") or 0.5)
                new_w = round(max(0.1, min(0.9, current_w + step)), 4)
                await db.users.update_one(
                    {"user_id": uid},
                    {"$set": {"exploration_weight": new_w}},
                )
    # Invalidate AFTER all mutations — invalidating before risked a concurrent
    # /discover rebuilding & re-caching from pre-swipe state, locking stale
    # data in for the full TTL.
    invalidate_discover_cache(uid)
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    # ── Persist consolidated taste snapshot (Task #23 Step 3) ────────────────
    # Denormalised view for the feed builder + diagnostics dashboard. Derived
    # from the freshly-mutated weight fields so it always reflects this swipe.
    if fresh:
        tp = build_taste_profile(fresh)
        await db.users.update_one({"user_id": uid}, {"$set": {"taste_profile": tp}})
        fresh["taste_profile"] = tp
    return public_user(fresh)


@router.post("/user/watched-feedback")
async def watched_feedback(payload: WatchedFeedbackIn, user: dict = Depends(require_user)):
    """Let a user change a watched-title rating later (Feature 1).

    Reverses the previously-applied sentiment delta (exactly), applies the new
    one, and updates the ``watched_feedback`` map. Returns the stored record.
    """
    uid = user["user_id"]
    movie = find_movie(payload.movie_id)
    if not movie:
        movie = await db.movies_cache.find_one({"id": payload.movie_id}, {"_id": 0})
    if not movie:
        raise HTTPException(404, "Movie not found")

    now_iso = datetime.now(timezone.utc).isoformat()
    delta = WATCHED_SENTIMENT_DELTAS[payload.watched_sentiment]
    new_inc = _taste_inc_for_delta(movie, user, delta)

    # Concurrency-safe re-rate: atomically CLAIM the prior feedback entry
    # ($unset the map key, return the pre-image) so concurrent re-rates each see
    # the latest committed record and converge (no double-apply / missed
    # reversal). Then apply (reverse_prior + new_delta) as ONE combined $inc plus
    # a $set of the new record in a single update.
    _fb_key = f"watched_feedback.{payload.movie_id}"
    _claim = await db.users.find_one_and_update(
        {"user_id": uid},
        {"$unset": {_fb_key: ""}},
        projection={"_id": 0, _fb_key: 1},
        return_document=ReturnDocument.BEFORE,
    ) or {}
    prev = (_claim.get("watched_feedback") or {}).get(payload.movie_id)
    combined = dict(new_inc)
    if prev and isinstance(prev, dict) and prev.get("applied_inc"):
        for k, v in _negate_inc(prev["applied_inc"]).items():
            combined[k] = round(combined.get(k, 0) + v, 4)

    record = {
        "sentiment": payload.watched_sentiment,
        "completed": bool(payload.completed),
        "delta": delta,
        "applied_inc": new_inc,
        "at": now_iso,
    }
    # Ensure the title is marked watched (a later re-rating should imply it) and
    # persist the new record + combined weight delta in a single update.
    _upd: dict = {
        "$addToSet": {"watched": payload.movie_id},
        "$set": {_fb_key: record},
    }
    if combined:
        _upd["$inc"] = combined
    await db.users.update_one({"user_id": uid}, _upd)
    await db.user_actions.insert_one({
        "user_id": uid, "movie_id": payload.movie_id, "action": "watched_feedback",
        "watched_sentiment": payload.watched_sentiment, "completed": bool(payload.completed),
        "sentiment_delta": delta, "applied_inc": new_inc, "created_at": now_iso,
    })
    invalidate_insights_cache(uid)
    invalidate_discover_cache(uid)

    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if fresh:
        tp = build_taste_profile(fresh)
        await db.users.update_one({"user_id": uid}, {"$set": {"taste_profile": tp}})

    # Return the stored record (public-safe — no applied_inc internals needed by
    # the client, but include them for debugging parity with the audit doc).
    return {"ok": True, "movie_id": payload.movie_id, "record": record}


@router.post("/user/progress")
async def set_progress(payload: ProgressIn, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if movie and movie.get("type") == "tv" and movie.get("seasons"):
        season_obj = next((s for s in movie["seasons"] if s.get("season_number") == payload.season), None)
        if not season_obj:
            raise HTTPException(400, f"Season {payload.season} not found")
        max_ep = season_obj.get("episode_count") or 999
        if payload.episode > max_ep:
            raise HTTPException(400, f"Episode exceeds season max ({max_ep})")
    key = episode_key(payload.season, payload.episode)
    now = datetime.now(timezone.utc).isoformat()
    # Keep the historical coarse cursor as well as the canonical episode map.
    # $set makes retries idempotent and is safe for clients that only understand
    # season/episode.
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            f"progress.{payload.movie_id}.season": payload.season,
            f"progress.{payload.movie_id}.episode": payload.episode,
            f"progress.{payload.movie_id}.updated_at": now,
            f"progress.{payload.movie_id}.episodes.{key}": {
                "watched": True, "provenance": "explicit", "updated_at": now
            },
            f"progress.{payload.movie_id}.provenance": "explicit",
        }},
    )
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return public_user(fresh)


@router.post("/user/progress/episode")
async def set_episode_progress(payload: EpisodeProgressIn, user: dict = Depends(require_user)):
    """Set one canonical episode state; repeated writes have no side effects."""
    key = episode_key(payload.season, payload.episode)
    now = datetime.now(timezone.utc).isoformat()
    entry = {"watched": bool(payload.watched), "provenance": payload.provenance,
             "updated_at": now}
    update = {f"progress.{payload.movie_id}.episodes.{key}": entry,
              f"progress.{payload.movie_id}.updated_at": now}
    if payload.watched:
        update.update({
            f"progress.{payload.movie_id}.season": payload.season,
            f"progress.{payload.movie_id}.episode": payload.episode,
        })
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    return {"ok": True, "movie_id": payload.movie_id, "episode_key": key, "progress": entry}


@router.post("/user/progress/watched-through")
async def watched_through(payload: ProgressIn, user: dict = Depends(require_user)):
    """Mark episodes through a cursor as inferred, without fabricating metadata."""
    now = datetime.now(timezone.utc).isoformat()
    # A bounded range is intentional: absent TMDB season metadata we only know
    # the requested season/cursor, never a season's total episode count.
    movie = find_movie(payload.movie_id)
    if not movie:
        movie = await db.movies_cache.find_one({"id": payload.movie_id}, {"_id": 0})
    movie = await _hydrate_progress_movie(movie)
    updates = {}
    # Include all earlier known seasons.  Unknown seasons are deliberately not
    # guessed; the requested cursor itself remains valid legacy-compatible data.
    known_seasons = (movie or {}).get("seasons") or []
    existing_eps = normalize_progress(
        (user.get("progress") or {}).get(payload.movie_id)
    ).get("episodes", {})
    def _bulk_set(season_no: int, ep: int):
        key = episode_key(season_no, ep)
        prior = existing_eps.get(key) or {}
        if isinstance(prior, dict) and prior.get("provenance") in {"explicit", "explicit_correction"}:
            return
        updates[f"progress.{payload.movie_id}.episodes.{key}"] = {
            "watched": True, "provenance": "bulk_inferred", "updated_at": now
        }
    today = date.today().isoformat()
    for season_obj in known_seasons:
        season_no = int(season_obj.get("season_number") or 0)
        count = int(season_obj.get("episode_count") or 0)
        detailed = season_obj.get("episodes") or []
        if detailed and 0 < season_no <= payload.season:
            for episode in detailed:
                ep = int(episode.get("episode_number") or 0)
                if (ep > 0 and episode.get("air_date")
                        and episode["air_date"] <= today
                        and (season_no < payload.season or ep <= payload.episode)):
                    _bulk_set(season_no, ep)
        elif 0 < season_no < payload.season and count > 0:
            for ep in range(1, count + 1):
                _bulk_set(season_no, ep)
    target = next((s for s in known_seasons
                   if int(s.get("season_number") or 0) == payload.season), None)
    if not (target or {}).get("episodes"):
        for ep in range(1, payload.episode + 1):
            _bulk_set(payload.season, ep)
    updates.update({
        f"progress.{payload.movie_id}.season": payload.season,
        f"progress.{payload.movie_id}.episode": payload.episode,
        f"progress.{payload.movie_id}.updated_at": now,
        f"progress.{payload.movie_id}.provenance": "bulk_inferred",
    })
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": updates})
    return {"ok": True, "movie_id": payload.movie_id, "through": {
        "season": payload.season, "episode": payload.episode
    }, "provenance": "bulk_inferred"}


@router.post("/user/progress/season")
@router.post("/user/progress/mark-season")
async def season_progress(payload: ProgressIn, user: dict = Depends(require_user)):
    """Mark a complete known season, excluding TMDB specials."""
    movie = find_movie(payload.movie_id) or await db.movies_cache.find_one(
        {"id": payload.movie_id}, {"_id": 0})
    movie = await _hydrate_progress_movie(movie)
    season = next((s for s in ((movie or {}).get("seasons") or [])
                   if int(s.get("season_number") or 0) == payload.season), None)
    episodes = (season or {}).get("episodes") or []
    today = date.today().isoformat()
    aired_numbers = [int(e.get("episode_number") or 0) for e in episodes
                     if e.get("air_date") and e["air_date"] <= today]
    count = max(aired_numbers, default=0) if episodes else int(
        (season or {}).get("episode_count") or 0)
    if not season or count <= 0:
        raise HTTPException(422, "Season episode metadata is unavailable")
    return await watched_through(
        ProgressIn(movie_id=payload.movie_id, season=payload.season, episode=count),
        user,
    )


@router.post("/user/progress/currently-available")
@router.post("/user/progress/mark-currently-available")
@router.post("/user/progress/current")
async def mark_currently_available(payload: ProgressIn, user: dict = Depends(require_user)):
    """Mark all currently listed, non-special episodes of a series watched."""
    movie = find_movie(payload.movie_id) or await db.movies_cache.find_one(
        {"id": payload.movie_id}, {"_id": 0})
    movie = await _hydrate_progress_movie(movie)
    seasons = [s for s in ((movie or {}).get("seasons") or [])
               if int(s.get("season_number") or 0) > 0]
    if not seasons or any(int(s.get("episode_count") or 0) <= 0 for s in seasons):
        raise HTTPException(409, "Series episode metadata is unavailable")
    today = date.today().isoformat()
    available = []
    for season in seasons:
        episodes = season.get("episodes") or []
        if not episodes:
            continue
        aired = [int(e.get("episode_number") or 0) for e in episodes
                 if e.get("air_date") and e["air_date"] <= today]
        if aired:
            available.append((int(season["season_number"]), max(aired)))
    if not available:
        raise HTTPException(409, "Released episode metadata is unavailable")
    last_season, last_episode = max(available)
    return await watched_through(
        ProgressIn(movie_id=payload.movie_id, season=last_season,
                   episode=last_episode), user)


@router.post("/user/progress/toggle")
async def toggle_episode(payload: EpisodeProgressIn, user: dict = Depends(require_user)):
    """Explicit episode toggle. Uses the current state and atomically replaces it."""
    key = episode_key(payload.season, payload.episode)
    old = ((user.get("progress") or {}).get(payload.movie_id) or {})
    current = normalize_progress(old).get("episodes", {}).get(key, {})
    watched = not bool(current.get("watched"))
    now = datetime.now(timezone.utc).isoformat()
    entry = {"watched": watched, "provenance": "explicit", "updated_at": now}
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {
        f"progress.{payload.movie_id}.episodes.{key}": entry,
        f"progress.{payload.movie_id}.updated_at": now,
    }})
    return {"ok": True, "movie_id": payload.movie_id, "episode_key": key, "watched": watched}


@router.post("/user/engage")
async def user_engage(payload: EngageIn, user: dict = Depends(require_user)):
    """Lightweight engagement signal — does NOT touch saved/watched/skipped lists.

    Signals and their weights:
      trailer_open  → stronger intent (0.4 per genre, 0.2 type)
      detail_view   → moderate intent (0.15 per genre, 0.1 type)
      search_click  → light interest (0.1 per genre, 0.05 type)
    """
    WEIGHTS = {
        "trailer_open": {"genre": 0.4, "type": 0.2},
        "detail_view":  {"genre": 0.15, "type": 0.1},
        "search_click": {"genre": 0.1,  "type": 0.05},
    }
    w = WEIGHTS.get(payload.action)
    if not w:
        return {"ok": False, "reason": "unknown_action"}

    movie = find_movie(payload.movie_id)
    if not movie:
        movie = await db.movies_cache.find_one({"id": payload.movie_id}, {"_id": 0})
    if not movie:
        return {"ok": False, "reason": "movie_not_found"}

    inc = {}
    genres = movie.get("genres") or []
    genre_count = max(1, len(genres))
    for g in genres:
        inc[f"genre_weights.{g}"] = round(w["genre"] / genre_count, 4)
    inc[f"type_weights.{movie.get('type', 'movie')}"] = w["type"]

    # ── Behavioral depth: tone/pacing/theme from soft engagement ─────────────
    # Engagement signals (trailer, detail view) are weaker than explicit swipes
    # so we use 30%/20%/10% of the genre weight rather than the action weights.
    card = movie.get("card") or {}
    tone = card.get("tone")
    if tone and tone != "neutral":
        inc[f"tone_weights.{tone}"] = round(w["genre"] * 0.30, 4)
    pacing = card.get("pacing")
    if pacing and pacing != "medium":
        inc[f"pacing_weights.{pacing}"] = round(w["genre"] * 0.20, 4)
    for theme in (card.get("verified_themes") or card.get("themes") or [])[:2]:
        inc[f"theme_weights.{theme}"] = round(w["genre"] * 0.10, 4)

    lang = movie.get("original_language")
    if lang:
        inc[f"language_weights.{lang}"] = round(w["genre"] * 0.25, 4)
    _year = movie.get("year")
    if _year:
        _decade = f"{(_year // 10) * 10}s"
        inc[f"decade_weights.{_decade}"] = round(w["genre"] * 0.15, 4)

    uid = user["user_id"]
    await db.users.update_one({"user_id": uid}, {"$inc": inc})
    # Engagement signals shift weights — drop cached feed for next /discover.
    invalidate_discover_cache(uid)
    _engage_row = {
        "user_id": uid,
        "movie_id": payload.movie_id,
        "action": payload.action,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.impression_id:
        _engage_row["impression_id"] = payload.impression_id
    await db.user_actions.insert_one(_engage_row)
    # ── Trigger incremental community-metric refresh (Task #38) ───────────
    from global_learning import schedule_update_title_metrics
    schedule_update_title_metrics(payload.movie_id)
    return {"ok": True}


@router.get("/user/suppression-debug")
async def suppression_debug(user: dict = Depends(require_user)):
    """Return every actively suppressed category with reason, strength, and confidence.

    Complements taste-debug with a focused view on what the engine is
    actively filtering OUT — useful for explaining why certain content
    stopped appearing after repeated skips.
    """
    from engine import _confidence_tier, _neg_maturity

    LANG_NAMES = {
        "en": "English", "ja": "Japanese", "ko": "Korean", "fr": "French",
        "de": "German", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
        "zh": "Chinese", "hi": "Hindi", "th": "Thai", "ru": "Russian",
        "ar": "Arabic", "sv": "Swedish", "da": "Danish", "nl": "Dutch",
        "pl": "Polish", "tr": "Turkish", "no": "Norwegian", "fi": "Finnish",
    }

    nm = _neg_maturity(user)
    tier = _confidence_tier(user)
    total = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )

    lw  = user.get("language_weights") or {}
    dw  = user.get("decade_weights") or {}
    tw  = user.get("tone_weights") or {}
    thw = user.get("theme_weights") or {}

    # Auto-blocked (hard pool filter — title never reaches scoring)
    auto_blocked_langs   = list(user.get("auto_blocked_languages") or [])
    auto_blocked_decades = list(user.get("auto_blocked_decades") or [])

    def _suppression_strength(weight: float, denominator: float, ceiling: float) -> str:
        import math
        score = abs(math.tanh(weight / denominator) * ceiling * nm)
        if score >= ceiling * 0.95:  return "maximum"
        if score >= ceiling * 0.70:  return "strong"
        if score >= ceiling * 0.40:  return "moderate"
        return "mild"

    suppressed_languages = [
        {
            "language":  LANG_NAMES.get(k, k),
            "code":      k,
            "weight":    round(v, 2),
            "strength":  _suppression_strength(v, 2.0, 5.0),
            "hard_blocked": k in auto_blocked_langs,
            "skips_approx": max(1, round(abs(v) / 1.0)),
        }
        for k, v in sorted(lw.items(), key=lambda x: x[1])
        if v < -1.5
    ]

    suppressed_decades = [
        {
            "decade":   k,
            "weight":   round(v, 2),
            "strength": _suppression_strength(v, 2.0, 3.5),
            "hard_blocked": k in auto_blocked_decades,
            "skips_approx": max(1, round(abs(v) / 0.8)),
        }
        for k, v in sorted(dw.items(), key=lambda x: x[1])
        if v < -1.0
    ]

    suppressed_tones = [
        {
            "tone":     k,
            "weight":   round(v, 2),
            "strength": _suppression_strength(v, 3.0, 2.5),
        }
        for k, v in sorted(tw.items(), key=lambda x: x[1])
        if v < -0.8
    ]

    suppressed_themes = [
        {
            "theme":    k,
            "weight":   round(v, 2),
            "strength": _suppression_strength(v, 3.0, 2.5),
        }
        for k, v in sorted(thw.items(), key=lambda x: x[1])
        if v < -0.8
    ]

    # ── Top liked signals (Task #7 — complete picture of learned taste) ──────
    gw = user.get("genre_weights") or {}
    top_liked_genres = [
        {"genre": k, "weight": round(v, 2)}
        for k, v in sorted(gw.items(), key=lambda x: x[1], reverse=True)[:5]
        if v > 0.5
    ]
    top_liked_themes = [
        {"theme": k, "weight": round(v, 2)}
        for k, v in sorted(thw.items(), key=lambda x: x[1], reverse=True)[:5]
        if v > 0.3
    ]
    top_liked_tones = [
        {"tone": k, "weight": round(v, 2)}
        for k, v in sorted(tw.items(), key=lambda x: x[1], reverse=True)[:3]
        if v > 0.3
    ]

    return {
        "confidence_tier":      tier,
        "total_interactions":   total,
        "neg_maturity":         round(nm, 3),
        "hard_blocked": {
            "languages": [LANG_NAMES.get(l, l) for l in auto_blocked_langs],
            "decades":   auto_blocked_decades,
        },
        "top_liked_genres":     top_liked_genres,
        "top_liked_themes":     top_liked_themes,
        "top_liked_tones":      top_liked_tones,
        "suppressed_languages": suppressed_languages,
        "suppressed_decades":   suppressed_decades,
        "suppressed_tones":     suppressed_tones,
        "suppressed_themes":    suppressed_themes,
        "notes": {
            "hard_blocked":   "These are removed from the candidate pool before scoring — they will never appear unless the user manually saves one.",
            "soft_suppressed": f"These carry a scoring penalty (up to −5.0 pts for language, −3.5 for decade) at current neg_maturity={nm:.2f}.",
            "auto_unblock":   "Hard blocks are removed automatically if the user saves/watches content in that category.",
        },
    }


@router.get("/user/why")
async def why_card(movie_id: str, user: dict = Depends(require_user)):
    """Per-card explainer (Task #7).

    Returns a structured "why this card was shown OR why it would be rejected"
    breakdown for a given movie_id. Mirrors the actual filter cascade in
    engine.build_feed / core.movie_matches so the answer matches what the
    user is really seeing.
    """
    import os
    from engine import _recently_shown_active, _eligible_skip_reintros
    from core import _is_family_kids, _is_anime, _is_bollywood

    movie = find_movie(movie_id)
    if not movie:
        movie = await db.movies_cache.find_one({"id": movie_id}, {"_id": 0})
    if not movie:
        raise HTTPException(404, "Movie not found")

    mg           = set(movie.get("genres") or [])
    card         = movie.get("card") or {}
    movie_tone   = card.get("tone", "neutral")
    movie_lang   = movie.get("original_language") or "en"
    movie_year   = movie.get("year") or 0
    movie_decade = f"{(movie_year // 10) * 10}s" if movie_year else None

    onboard_genres = set(user.get("genres") or [])
    gw  = user.get("genre_weights")    or {}
    tw  = user.get("tone_weights")     or {}
    lw  = user.get("language_weights") or {}
    dw  = user.get("decade_weights")   or {}
    thw = user.get("theme_weights")    or {}

    auto_blocked_langs   = set(user.get("auto_blocked_languages") or [])
    auto_blocked_decades = set(user.get("auto_blocked_decades") or [])
    user_subs            = set(user.get("subscriptions") or [])
    movie_subs           = set(movie.get("available_on") or [])
    excluded_cats        = set(user.get("excluded_categories") or [])
    excluded_genres      = set(user.get("excluded_genres") or [])
    user_region          = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()

    rejection_reasons: list[str] = []

    # ── 0. Catalog quality gate (matches build_feed) ─────────────────────────
    if not catalog_quality_gate(movie, user_region=user_region, user=user):
        rejection_reasons.append("failed_quality_gate")
        # Specific age-gate sub-reason so the admin knows WHY quality gate rejected
        yr = int(movie.get("year") or 0)
        if yr and yr < (2000 if movie.get("type") == "movie" else 1995):
            if not _classic_exception_ok(movie, user=user):
                rejection_reasons.append(f"year_below_floor:{yr}<{2000 if movie.get('type')=='movie' else 1995}")
            else:
                rejection_reasons.append("year_below_floor_but_classic_exception_ok")

    # ── 1-3. Excluded audience categories ────────────────────────────────────
    if ("family" in excluded_cats or "kids" in excluded_cats) and _is_family_kids(movie):
        rejection_reasons.append("excluded_category:family_kids")
    if "anime" in excluded_cats and _is_anime(movie):
        rejection_reasons.append("excluded_category:anime")
    if "bollywood" in excluded_cats and _is_bollywood(movie):
        rejection_reasons.append("excluded_category:bollywood")

    # ── 4. Subscription filter (strict mode) ─────────────────────────────────
    if user_subs and not (movie_subs & user_subs):
        rejection_reasons.append("not_on_user_subscriptions")

    # ── 5. Content type filter ───────────────────────────────────────────────
    content_type = user.get("content_type")
    if content_type and content_type != "both" and movie.get("type") != content_type:
        rejection_reasons.append(f"content_type_mismatch:wants_{content_type}")

    # ── 6. Excluded genres ────────────────────────────────────────────────────
    if excluded_genres & mg:
        rejection_reasons.append(f"excluded_genres:{sorted(excluded_genres & mg)}")

    # ── 7. International filter ──────────────────────────────────────────────
    if not user.get("show_international", True) and movie_lang != "en":
        rejection_reasons.append(f"english_only_active:lang={movie_lang}")

    # ── 8. Year range filter (mirrors core.movie_matches step 8) ─────────────
    yr_range = user.get("year_range")
    if yr_range and yr_range != "any" and movie_year:
        from datetime import date as _date
        _now_yr = _date.today().year
        if yr_range == "recent_only" and _now_yr - movie_year > 5:
            rejection_reasons.append("year_outside_range:recent_only")
        elif yr_range == "last_10" and _now_yr - movie_year > 10:
            rejection_reasons.append("year_outside_range:last_10")

    # ── 9. Learned hard blocks ───────────────────────────────────────────────
    if movie_lang in auto_blocked_langs:
        rejection_reasons.append(f"hard_blocked_language:{movie_lang}")
    if movie_decade and movie_decade in auto_blocked_decades:
        rejection_reasons.append(f"hard_blocked_decade:{movie_decade}")

    # ── 10. Already-touched suppression (matches build_feed permanently_seen) ─
    if movie_id in (user.get("saved") or []):
        rejection_reasons.append("already_saved")
    if movie_id in (user.get("watched") or []):
        rejection_reasons.append("already_watched")
    if movie_id in (user.get("onboarding_rated") or []):
        rejection_reasons.append("already_rated_in_onboarding")

    # ── 11. Recently-shown cooldown (168h LRU) ───────────────────────────────
    if movie_id in _recently_shown_active(user):
        rejection_reasons.append("recently_shown_cooldown_active")

    # ── 12. Skipped: build_feed rejects unless reintro-eligible ──────────────
    # Eligible reintros are NOT a rejection — only ineligible skips block the
    # card. Eligible ones become a positive info signal further down.
    reintro_eligible_here = False
    if movie_id in (user.get("skipped") or []):
        learned_top = {
            g for g, v in sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:3]
            if v >= 2
        }
        reintro = await _eligible_skip_reintros(user, learned_top)
        if movie_id not in reintro:
            rejection_reasons.append("previously_skipped_not_yet_eligible_for_reintro")
        else:
            reintro_eligible_here = True

    shown_reasons: list[str] = []
    if mg & onboard_genres:
        shown_reasons.append(f"matches_onboarding_genres:{sorted(mg & onboard_genres)}")
    learned_positive = [g for g in mg if gw.get(g, 0) >= 2]
    if learned_positive:
        shown_reasons.append(f"strong_learned_genres:{learned_positive}")
    if movie_tone != "neutral" and tw.get(movie_tone, 0) > 0.5:
        shown_reasons.append(f"liked_tone:{movie_tone}={round(tw[movie_tone], 2)}")
    liked_themes = [t for t in (card.get("themes") or []) if thw.get(t, 0) > 0.3]
    if liked_themes:
        shown_reasons.append(f"liked_themes:{liked_themes}")
    if user_subs and (movie_subs & user_subs):
        shown_reasons.append(f"on_subscription:{sorted(movie_subs & user_subs)}")
    if reintro_eligible_here:
        shown_reasons.append("previously_skipped_but_reintro_eligible")

    soft_penalties: list[dict] = []
    if movie_tone != "neutral" and tw.get(movie_tone, 0) < -0.8:
        soft_penalties.append({"signal": f"tone:{movie_tone}",
                               "weight": round(tw[movie_tone], 2)})
    if lw.get(movie_lang, 0) < -1.5:
        soft_penalties.append({"signal": f"language:{movie_lang}",
                               "weight": round(lw[movie_lang], 2)})
    if movie_decade and dw.get(movie_decade, 0) < -1.0:
        soft_penalties.append({"signal": f"decade:{movie_decade}",
                               "weight": round(dw[movie_decade], 2)})
    disliked_themes = [
        {"signal": f"theme:{t}", "weight": round(thw[t], 2)}
        for t in (card.get("themes") or []) if thw.get(t, 0) < -0.8
    ]
    soft_penalties.extend(disliked_themes)

    return {
        "movie_id":         movie_id,
        "title":            movie.get("title"),
        "year":             movie_year,
        "genres":           sorted(mg),
        "tone":             movie_tone,
        "language":         movie_lang,
        "decade":           movie_decade,
        "available_on":     sorted(movie_subs),
        "would_be_rejected": bool(rejection_reasons),
        "rejection_reasons": rejection_reasons,
        "shown_reasons":     shown_reasons,
        "soft_penalties":    soft_penalties,
        "age_tier":           _age_tier(movie),
        "classic_exception":  _classic_exception_ok(movie, user=user),
    }


@router.get("/user/taste-debug")
async def taste_debug(user: dict = Depends(require_user)):
    """Return a breakdown of everything the engine has learned about this user.

    Useful for understanding why certain content keeps appearing or
    disappearing — surfaces the raw learned weights with human-readable labels.
    """
    LANG_NAMES = {
        "en": "English", "ja": "Japanese", "ko": "Korean", "fr": "French",
        "de": "German", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
        "zh": "Chinese", "hi": "Hindi", "th": "Thai", "ru": "Russian",
        "ar": "Arabic", "sv": "Swedish", "da": "Danish", "nl": "Dutch",
        "pl": "Polish", "tr": "Turkish", "no": "Norwegian", "fi": "Finnish",
    }

    total_interactions = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    maturity = min(1.0, total_interactions / 50.0)

    def _split(d: dict, name_map: "dict | None" = None, top: int = 12):
        renamed = {name_map.get(k, k): v for k, v in d.items()} if name_map else d
        items = sorted(renamed.items(), key=lambda x: x[1], reverse=True)
        liked    = {k: round(v, 2) for k, v in items if v > 0}
        disliked = {k: round(v, 2) for k, v in reversed(items) if v < 0}
        return {"liked": dict(list(liked.items())[:top]), "disliked": dict(list(disliked.items())[:top])}

    gw  = user.get("genre_weights")   or {}
    lw  = user.get("language_weights") or {}
    dw  = user.get("decade_weights")   or {}
    thw = user.get("theme_weights")    or {}
    tw  = user.get("tone_weights")     or {}
    pw  = user.get("pacing_weights")   or {}

    pct = round(maturity * 100)
    remaining = max(0, 50 - total_interactions)
    if maturity >= 1.0:
        note = "Feed fully personalised — all learned signals at full strength."
    elif remaining <= 10:
        note = f"Almost there ({pct}% personalised) — {remaining} more swipes to unlock full strength."
    else:
        note = f"{pct}% personalised — {remaining} more swipes to unlock full signal strength."

    return {
        "maturity":            round(maturity, 3),
        "total_interactions":  total_interactions,
        "personalisation_note": note,
        "content_controls": {
            "show_international": user.get("show_international", True),
            "year_range":         user.get("year_range", "any"),
        },
        "genre_weights":    _split(gw),
        "language_weights": _split(lw, name_map=LANG_NAMES),
        "decade_weights":   _split(dw),
        "theme_weights":    _split(thw),
        "tone_weights":     _split(tw),
        "pacing_weights":   _split(pw),
        "exploration_weight": round(float(user.get("exploration_weight") or 0.5), 3),
        "top_negative_signals": sorted(
            [
                {"signal": f"genre:{k}", "weight": round(v, 2)}
                for k, v in gw.items() if v < -2
            ] + [
                {"signal": f"lang:{LANG_NAMES.get(k, k)}", "weight": round(v, 2)}
                for k, v in lw.items() if v < -2
            ] + [
                {"signal": f"decade:{k}", "weight": round(v, 2)}
                for k, v in dw.items() if v < -2
            ] + [
                {"signal": f"theme:{k}", "weight": round(v, 2)}
                for k, v in thw.items() if v < -1
            ],
            key=lambda x: x["weight"]
        )[:15],
    }


@router.get("/watchlist")
async def watchlist(user: dict = Depends(require_user)):
    return movies_by_ids(user.get("saved") or [])


@router.post("/user/watchlist-seen")
async def watchlist_seen(user: dict = Depends(require_user)):
    """Clear the unseen-watchlist badge counter (user opened the Watchlist)."""
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"watchlist_unseen": 0}},
    )
    return {"watchlist_unseen": 0}


@router.get("/watched")
async def watched(user: dict = Depends(require_user)):
    return movies_by_ids(user.get("watched") or [])


async def _library_records(ids: list[str], user: dict, type_filter: str | None = None) -> list[dict]:
    """Hydrate IDs while retaining missing/legacy IDs out of the response."""
    progress = user.get("progress") or {}
    catalog_rows = [
        movie for movie in movies_by_ids(ids)
        if not type_filter or type_filter == "both" or movie.get("type") == type_filter
    ]

    async def hydrate(movie: dict) -> dict:
        item = dict(movie)
        feedback = (user.get("watched_feedback") or {}).get(movie.get("id"))
        if isinstance(feedback, dict):
            if feedback.get("sentiment"):
                item["you_reaction"] = feedback["sentiment"]
            if "completed" in feedback:
                item["watched_completed"] = bool(feedback["completed"])
        if (item.get("type") == "tv" and item.get("tmdb_id")
                and item.get("seasons") and movie.get("id") in progress):
            item["seasons"] = await hydrate_tv_seasons(
                int(item["tmdb_id"]), item.get("seasons"))
        if movie.get("id") in progress:
            item["progress"] = normalize_progress(progress[movie["id"]])
            item["completion"] = completion_metadata(
                item["progress"], item.get("seasons"), item.get("runtime"))
        return item

    # Different shows hydrate concurrently; tmdb.py enforces the global request
    # cap, so a large Library is faster without creating unbounded fan-out.
    out = list(await asyncio.gather(*(hydrate(movie) for movie in catalog_rows)))
    found = {m.get("id") for m in out}
    for mid in ids:
        if mid not in found:
            # Preserve history even if a catalog record was removed/unavailable.
            out.append({"id": mid, "title": "Unavailable title", "type": "unknown",
                        "unavailable": True})
    return out


@router.get("/library")
@router.get("/user/library")
async def library(type: Optional[Literal["movie", "tv", "both"]] = None,
                  user: dict = Depends(require_user)):
    """Unified hydrated library; old watchlist/watched endpoints are unchanged."""
    saved = await _library_records(user.get("saved") or [], user, type)
    watched_ids = list(user.get("watched") or [])
    # A progress record starts a show even for legacy clients that never added
    # the parent series to watched.
    for mid in (user.get("progress") or {}):
        if mid not in watched_ids:
            watched_ids.append(mid)
    watched_rows = await _library_records(watched_ids, user, type)
    all_progress = []
    for mid, rec in (user.get("progress") or {}).items():
        movie = await _library_records([mid], user, type)
        if movie and movie[0].get("type") == "tv":
            all_progress.append(movie[0])
    continue_rows = [
        m for m in all_progress
        if not (m.get("completion") or {}).get("completed")
    ]
    detailed_stats = await library_stats(type, user)
    stats = {
        "saved": len(saved), "watched": len(watched_rows),
        "in_progress": len(continue_rows),
        **detailed_stats,
    }
    return {"watchlist": saved, "saved": saved, "watched": watched_rows,
            "progress": all_progress, "continue_watching": continue_rows,
            "stats": stats}


@router.get("/library/stats")
async def library_stats(type: Optional[Literal["movie", "tv", "both"]] = None,
                        user: dict = Depends(require_user)):
    watched_ids = list(user.get("watched") or [])
    watched_ids.extend(mid for mid in (user.get("progress") or {})
                        if mid not in watched_ids)
    watched_rows = await _library_records(watched_ids, user, type)
    movie_count = sum(1 for m in watched_rows if m.get("type") == "movie")
    tv_rows = [m for m in watched_rows if m.get("type") == "tv"]
    explicit_eps = inferred_eps = 0
    total_hours = 0.0
    measured_hours = 0.0
    estimated_runtime_hours = 0.0
    estimated_hours = False
    completed_tv = 0
    # Progress is authoritative for episode counts even when the parent series
    # is not in the legacy watched list (older clients never added it).
    progress_rows = await _library_records(list((user.get("progress") or {}).keys()), user, type)
    for m in progress_rows:
        if m.get("type") != "tv":
            continue
        rec = normalize_progress(m.get("progress") or {})
        for value in rec.get("episodes", {}).values():
            if not value.get("watched"):
                continue
            if value.get("provenance") == "inferred":
                inferred_eps += 1
            else:
                explicit_eps += 1
        meta = completion_metadata(rec, m.get("seasons"), m.get("runtime"))
        if meta["completed"]:
            completed_tv += 1
        runtime = float(m.get("runtime") or 0)
        measured_minutes = float(meta.get("measured_runtime_minutes") or 0)
        measured_count = int(meta.get("measured_runtime_episode_count") or 0)
        estimated_count = max(0, watched_episode_count(rec) - measured_count)
        measured_hours += measured_minutes / 60.0
        estimated_runtime_hours += estimated_count * runtime / 60.0
        total_hours += (measured_minutes + estimated_count * runtime) / 60.0
        if runtime and estimated_count:
            estimated_hours = True
    for m in watched_rows:
        if m.get("type") == "movie" and m.get("runtime"):
            movie_hours = float(m["runtime"]) / 60.0
            measured_hours += movie_hours
            total_hours += movie_hours
    hours_provenance = ("mixed" if measured_hours and estimated_runtime_hours else
                        ("estimated" if estimated_runtime_hours else "measured"))
    return {"watched_movies": movie_count,
            "distinct_watched_movies": movie_count,
            "tv_shows_started": len(tv_rows),
            "tv_shows_completed": completed_tv,
            "watched_episodes": explicit_eps + inferred_eps,
            "explicit_episodes": explicit_eps, "inferred_episodes": inferred_eps,
            "total_hours": round(total_hours, 2),
            "measured_hours": round(measured_hours, 2),
            "estimated_runtime_hours": round(estimated_runtime_hours, 2),
            "total_hours_estimated": estimated_hours,
            "hours_provenance": hours_provenance,
            "estimated": bool(inferred_eps),
            "provenance": "mixed" if explicit_eps and inferred_eps else
                          ("inferred" if inferred_eps else "explicit")}


@router.get("/user/progress/{movie_id}")
async def series_progress(movie_id: str, user: dict = Depends(require_user)):
    """Return canonical progress for one series, including legacy cursor data."""
    record = normalize_progress((user.get("progress") or {}).get(movie_id))
    return {"movie_id": movie_id, "progress": record,
            "available": bool(record.get("episodes") or
                              (record.get("season") and record.get("episode")))}
