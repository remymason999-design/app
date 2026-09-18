"""Persistent taste profile (Task #23 Step 3).

Two pure helpers shared by the onboarding and swipe routers:

  * ``taste_learning_inc`` — given a movie and a signed learning delta, returns a
    Mongo ``$inc`` fragment that nudges the *soft* taste signals that were not
    previously learned: cast/director affinity, runtime, popularity and quality
    preference.  These are SCORING-ONLY weights — they never filter the pool.

  * ``build_taste_profile`` — derives a denormalised, human-readable snapshot of
    what we currently know about the user from their accumulated weight fields.
    Stored on ``user.taste_profile`` so the feed builder and the diagnostics
    dashboard (Task #24) can read a stable summary without recomputing it.

Both are deliberately additive and benefit-of-doubt: a missing field simply
contributes nothing rather than penalising a title or a user.
"""
from datetime import datetime, timezone


# Learning multipliers — gentle relative to the genre signal so a single swipe
# never lets one actor / runtime / popularity bucket dominate the feed.
_CAST_MULT       = 0.5
_DIRECTOR_MULT   = 0.4
_WRITER_MULT     = 0.3
_RUNTIME_MULT    = 0.3
_POPULARITY_MULT = 0.25
_QUALITY_MULT    = 0.25

# Skip dampening for people-based signals — a single skip must not heavily
# punish an actor/director/writer; only repeated skips of the same person
# gradually reduce affinity.  WATCHED and SAVED are stronger positive signals
# than skips are negative.
_PEOPLE_SKIP_DECAY = 0.55   # skip delta is multiplied by this before applying

# Explicit title ratings from onboarding are stored separately from post-onboarding
# behaviour.  They start at full strength, then fade only as a user gives the app
# genuine save/skip/watched evidence.  Explicitly selected genres are deliberately
# not part of these source maps: they remain an enduring stated preference.
ONBOARD_TASTE_DECAY = 1.0
ONBOARDING_DECAY_START = 20
ONBOARDING_DECAY_COMPLETE = 100
ONBOARDING_DECAY_FLOOR = 0.25


def onboarding_signal_decay(user: dict) -> float:
    """Return the live multiplier for explicit onboarding *title* responses.

    0–20 genuine post-onboarding actions retain the full training signal.
    From 20 to 100 it linearly reduces to 25%; thereafter it remains useful
    historical evidence but cannot dominate real behaviour.  New bookkeeping is
    intentionally additive: legacy users without it get 0 post-onboarding
    actions, and their existing weight maps are never changed.
    """
    count = max(0, int(user.get("post_onboarding_interactions") or 0))
    if count <= ONBOARDING_DECAY_START:
        return 1.0
    if count >= ONBOARDING_DECAY_COMPLETE:
        return ONBOARDING_DECAY_FLOOR
    progress = (count - ONBOARDING_DECAY_START) / (
        ONBOARDING_DECAY_COMPLETE - ONBOARDING_DECAY_START
    )
    return round(1.0 - (1.0 - ONBOARDING_DECAY_FLOOR) * progress, 4)


def effective_weight_map(user: dict, field: str) -> dict:
    """Combine legacy/behavioural weights with decayed onboarding title evidence.

    This is a scorer helper, not a migration.  Existing maps remain byte-for-byte
    intact and onboarding source maps only exist for newly trained users.
    """
    combined = {
        k: float(v) for k, v in (user.get(field) or {}).items()
        if isinstance(v, (int, float))
    }
    decay = onboarding_signal_decay(user)
    for key, value in (user.get(f"onboarding_{field}") or {}).items():
        if isinstance(value, (int, float)):
            combined[key] = combined.get(key, 0.0) + float(value) * decay
    return combined


def onboarding_weight_map(user: dict, field: str) -> dict:
    """Return only decayed onboarding-title evidence for one affinity field.

    The live scorer uses this for metadata axes that historically were stored
    for diagnostics but not ranked (director/writer/runtime/popularity/quality).
    Keeping it source-only makes the new bonuses fully backward-compatible:
    legacy generic maps keep their existing scoring semantics.
    """
    decay = onboarding_signal_decay(user)
    return {
        k: float(v) * decay for k, v in (user.get(f"onboarding_{field}") or {}).items()
        if isinstance(v, (int, float))
    }


def _runtime_bucket(runtime) -> str | None:
    if not runtime:
        return None
    if runtime < 95:
        return "short"
    if runtime > 125:
        return "long"
    return "medium"


def _popularity_bucket(pop) -> str | None:
    if pop is None:
        return None
    if pop < 10:
        return "niche"
    if pop > 50:
        return "popular"
    return "moderate"


def person_key(name: str) -> str:
    """Sanitize a person name for use as a Mongo map key.

    Mongo interprets dots in ``$inc`` field paths as nesting, so a name like
    "samuel l. jackson" would silently create ``cast_weights["samuel l"]
    ["jackson"]`` — corrupting the weights map (dict values where numbers are
    expected). Strip dots and leading '$' to keep keys flat and valid.
    """
    return str(name).lower().replace(".", "").lstrip("$").strip()


def _movie_cast(movie: dict) -> list[str]:
    card = movie.get("card") or {}
    cast = card.get("cast")
    if cast:
        return [str(c).lower() for c in cast]
    return [str(c).lower() for c in (movie.get("cast_names") or [])]


def _movie_directors(movie: dict) -> list[str]:
    return [str(c).lower() for c in (movie.get("director_names") or [])]


def _movie_writers(movie: dict) -> list[str]:
    return [str(c).lower() for c in (movie.get("writer_names") or [])]


def taste_learning_inc(
    movie: dict, delta: float, *, onboarding: bool = False, field_prefix: str = ""
) -> dict:
    """Return a ``$inc`` fragment for the soft taste signals.

    ``delta`` is the same signed weight the caller already applies to genres.
    Onboarding signals retain the caller's full weight.
    """
    if not delta:
        return {}
    if onboarding:
        delta = round(delta * ONBOARD_TASTE_DECAY, 4)

    inc: dict = {}
    card = movie.get("card") or {}

    # Actor/director/writer affinity — all skip-dampened so a single skip
    # doesn't heavily punish a person; only repeated skips accumulate.
    _people_delta = delta * _PEOPLE_SKIP_DECAY if delta < 0 else delta

    for c in _movie_cast(movie)[:3]:
        key = person_key(c)
        if key:
            inc[f"{field_prefix}cast_weights.{key}"] = round(_people_delta * _CAST_MULT, 4)

    for d in _movie_directors(movie)[:2]:
        key = person_key(d)
        if key:
            inc[f"{field_prefix}director_weights.{key}"] = round(_people_delta * _DIRECTOR_MULT, 4)

    # Writer affinity — same gentle skip handling
    for w in _movie_writers(movie)[:2]:
        key = person_key(w)
        if key:
            inc[f"{field_prefix}writer_weights.{key}"] = round(_people_delta * _WRITER_MULT, 4)

    rb = _runtime_bucket(movie.get("runtime"))
    if rb:
        inc[f"{field_prefix}runtime_weights.{rb}"] = round(delta * _RUNTIME_MULT, 4)

    pb = _popularity_bucket(movie.get("popularity"))
    if pb:
        inc[f"{field_prefix}popularity_weights.{pb}"] = round(delta * _POPULARITY_MULT, 4)

    qt = card.get("quality_tier")
    if qt:
        inc[f"{field_prefix}quality_pref_weights.{qt}"] = round(delta * _QUALITY_MULT, 4)

    return inc


def onboarding_learning_inc(movie: dict, delta: float) -> dict:
    """All score-supported onboarding-title dimensions in separate source maps."""
    if not delta:
        return {}
    prefix = "onboarding_"
    inc: dict = {}
    genres = movie.get("genres") or []
    per_genre = round(delta / max(1, len(genres)), 4)
    for genre in genres:
        inc[f"{prefix}genre_weights.{genre}"] = per_genre
    inc[f"{prefix}type_weights.{movie.get('type', 'movie')}"] = round(delta * 0.6, 4)

    card = movie.get("card") or {}
    tone = card.get("tone")
    if tone and tone != "neutral":
        inc[f"{prefix}tone_weights.{tone}"] = round(delta * 0.45, 4)
    pacing = card.get("pacing")
    if pacing and pacing != "medium":
        inc[f"{prefix}pacing_weights.{pacing}"] = round(delta * 0.30, 4)
    for theme in (card.get("verified_themes") or card.get("themes") or [])[:3]:
        inc[f"{prefix}theme_weights.{theme}"] = round(delta * 0.25, 4)
    language = movie.get("original_language")
    if language:
        inc[f"{prefix}language_weights.{language}"] = round(delta, 4)
    year = movie.get("year")
    if year:
        inc[f"{prefix}decade_weights.{(year // 10) * 10}s"] = round(delta * 0.8, 4)
    inc.update(taste_learning_inc(movie, delta, onboarding=True, field_prefix=prefix))
    return inc


def _top_keys(weights: dict | None, n: int, *, positive: bool = True) -> list[str]:
    if not weights:
        return []
    # Skip non-numeric values defensively — dotted person names once created
    # nested dicts inside these maps (see person_key), and a single corrupt
    # entry must not 500 the whole action pipeline.
    items = [
        (k, v) for k, v in weights.items()
        if isinstance(v, (int, float)) and (v > 0 if positive else True)
    ]
    items.sort(key=lambda kv: kv[1], reverse=True)
    return [k for k, _ in items[:n]]


def _argmax(weights: dict | None) -> str | None:
    """Relatively-highest bucket for an ordinal preference.

    Unlike the 'likes' lists, ordinal preferences (runtime / popularity /
    quality band) lean toward whichever bucket the user engaged with *most*,
    even when a skip-heavy user's weights are all net-negative.  Returns the
    max by raw value so the preference is always present once any swipe with
    that signal has landed.
    """
    if not weights:
        return None
    numeric = [(k, v) for k, v in weights.items() if isinstance(v, (int, float))]
    if not numeric:
        return None
    return max(numeric, key=lambda kv: kv[1])[0]


def build_taste_profile(user: dict) -> dict:
    """Derive the consolidated taste snapshot from a user's weight fields."""
    return {
        "genres": _top_keys(effective_weight_map(user, "genre_weights"), 6),
        "eras": _top_keys(effective_weight_map(user, "decade_weights"), 3),
        "languages": _top_keys(effective_weight_map(user, "language_weights"), 4),
        "runtime": _argmax(effective_weight_map(user, "runtime_weights")),
        "popularity_pref": _argmax(effective_weight_map(user, "popularity_weights")),
        "quality_pref": _argmax(effective_weight_map(user, "quality_pref_weights")),
        "cast_affinity": _top_keys(effective_weight_map(user, "cast_weights"), 8),
        "director_affinity": _top_keys(effective_weight_map(user, "director_weights"), 6),
        "writer_affinity": _top_keys(effective_weight_map(user, "writer_weights"), 6),
        "providers": list(user.get("subscriptions") or []),
        "content_type": user.get("content_type") or "any",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
