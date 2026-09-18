"""WatchSmart recommendation engine.

A continuous, self-improving discovery pipeline:

  1. Build a per-user candidate pool from the catalog by applying ALL user
     filters strictly (subscriptions, excluded categories, excluded genres,
     content type, and a sliding "recently shown" cooldown).
  2. Score every candidate with a hybrid model that blends:
       - title quality (rating + popularity, decaying as user matures)
       - explicit preferences (onboarding genres + moods)
       - learned behaviour (genre_weights / type_weights mutated by every swipe)
       - lightweight collaborative filtering — boost titles liked by users
         whose `genre_weights` vector is closest to ours
       - recency / freshness boost
  3. Inject 5-10% controlled randomness (within filters) so the feed never
     stagnates.
  4. Maintain `recently_shown` LRU on the user doc so we never serve the same
     card twice in quick succession; expired entries become eligible again,
     and previously-skipped items can re-enter via the cooldown re-introduction
     path if their genres now match the user's top weights.
  5. If the candidate pool drops below `LOW_WATER`, schedule a non-blocking
     TMDB top-up so the feed effectively never runs out.

Public surface:
    build_feed(user, limit) -> list[dict]
    record_shown(user_id, ids) -> coroutine that appends to recently_shown
"""
from __future__ import annotations

import asyncio
import uuid
import logging
import math
import os
import random
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

from core import (
    db, get_catalog, movie_matches, movie_matches_no_subs,
    catalog_quality_gate, _age_tier, _classic_exception_ok,
    tmdb_client, movie_match_pct,
)
from taste import effective_weight_map, onboarding_weight_map, person_key
from content_cards import franchise_matches

logger = logging.getLogger("watchsmart.engine")

# Thresholds & knobs (tune freely)
RECENTLY_SHOWN_MAX = 500          # max ids tracked per user (~5 large sessions)
RECENTLY_SHOWN_COOLDOWN_HRS = 168 # 7-day cooldown — titles return after a week
SKIP_COOLDOWN_DAYS = 30           # how long until a skipped item can return
RANDOM_INJECTION_PCT = 0.08       # 8% of returned slots are random-within-filter (fill path)
COLLAB_NEIGHBOURS = 5             # nearest users for collaborative bonus
COLLAB_BONUS = 1.5                # max boost from collaborative signal
LOW_WATER = 300                   # below this, schedule a background TMDB top-up
TARGET_POOL = 2000                # target unseen+filtered pool size per user
POOL_THIN_THRESHOLD = 60          # core pool below this activates thin-pool mode + adaptive cooldown
CORE_CRITICAL_THRESHOLD = 15      # core pool below this triggers cross-subscription expansion
POOL_FLOOR = 100                  # broaden within filters to keep the pool above this when catalogue allows

# ── Catalogue-quality blend (Task #23) ───────────────────────────────────────
# Soft re-rank weights only — none of these filter the pool.
QUALITY_WEIGHT = 2.0              # additive nudge from the 0-100 card quality score
QUALITY_PIVOT = 0.55             # centre point (~Tier B) so average titles net ~0
QUALITY_TIER_D_PENALTY = 1.5     # extra demotion for the weakest tier (never removal)
CAST_AFFINITY_WEIGHT = 1.6       # max boost from learned actor/director affinity
HEAVY_USER_SWIPES = 500          # ≥ this many interactions ⇒ heavy-user mode
HEAVY_FRESH_FLOOR = 100          # …or fewer than this many fresh eligible titles
HEAVY_REINTRO_PENALTY = 4.0      # heavy users: deprioritise reintroduced/seen below fresh
LAST_RESORT_PENALTY = 1000.0     # Tier-D + skipped + weak-taste ⇒ absolute bottom (still in pool)

# ---------------------------------------------------------------------------
# Reality-TV suppression
# ---------------------------------------------------------------------------
# Reality TV / dating / celebrity / game-show content is suppressed from
# Discover unless the user explicitly selected it at onboarding OR their
# learned genre weight shows they repeatedly like it.  This keeps the feed
# trustworthy for the vast majority who never asked for reality content.
REALITY_GENRES = frozenset({"Reality", "Talk"})
REALITY_LIKE_THRESHOLD = 3.0      # learned genre weight above which reality is "repeatedly liked"
REALITY_KEYWORDS = (
    "dating show", "love island", "the bachelor", "bachelorette",
    "kardashian", "real housewives", "big brother", "married at first sight",
    "reality competition", "reality series", "reality show", "reality tv",
    "celebrity contestants", "game show",
)

# ---------------------------------------------------------------------------
# Exploration quality floor
# ---------------------------------------------------------------------------
# Adjacent/wildcard candidates must clear a quality bar so niche / obscure
# low-vote filler never dominates the broadening pool.  Core (the user's
# explicit genre) is never subject to this floor.
EXPLORE_VOTE_FLOOR = 50           # adjacent/wildcard need this many votes …
EXPLORE_RATING_FLOOR = 7.3        # …unless they are highly rated …
EXPLORE_POPULARITY_FLOOR = 20.0   # …or demonstrably popular.

# First N feed cards prioritise trust (core + high-confidence) over
# exploration — no wildcard cards appear before this position.
TRUST_HEAD = 30

_REFILL_LOCK: dict = {}            # user_id -> asyncio.Task to dedupe refills
_REFILL_COUNT: dict[str, int] = {} # user_id → lifetime refill trigger count (resets on restart)


# Per-genre TMDB popularity-compensation.  Several genres score 2–30 pop vs
# 100–500 for blockbusters, causing them to be buried in mixed feeds without an
# explicit boost.  Tuple: (onboarding_boost × maturity_decay, learned_flat_boost).
NICHE_GENRE_BOOSTS: dict[str, tuple[float, float]] = {
    "Documentary": (6.0, 1.5),   # pop 2-20 vs 100-500 for mainstream films
    "Horror":      (4.0, 1.5),   # budget films; limited TMDB vote base
    "Western":     (5.0, 2.0),   # very niche; older catalogue dominates ranking
    "War":         (4.0, 1.5),   # historical niche; limited modern viewership
    "Music":       (4.0, 1.5),   # small streaming catalogue; specialist audience
    "Mystery":     (2.0, 1.0),   # moderately niche; partially mixed with mainstream
    "Animation":   (1.5, 0.5),   # TV animation underrated vs film popularity scores
}

# ---------------------------------------------------------------------------
# Controlled variety — adjacent genre mapping
# ---------------------------------------------------------------------------
# Maps each genre to curated thematically related genres.
# Used to build the "adjacent" tier (~17% of feed) — keeps variety connected
# to the user's intent.  Genres outside this map become "wildcard" (~8%).
ADJACENT_GENRES: dict[str, list[str]] = {
    "Documentary":  ["History", "Biography", "Crime", "News", "Sport"],
    "Action":       ["Thriller", "Adventure", "Crime", "War", "Sci-Fi"],
    "Comedy":       ["Romance", "Family", "Animation", "Music"],
    "Drama":        ["Romance", "History", "Biography", "Crime", "Music"],
    "Horror":       ["Mystery", "Thriller", "Crime", "Sci-Fi"],
    "Sci-Fi":       ["Action", "Adventure", "Mystery", "Thriller", "Fantasy"],
    "Thriller":     ["Crime", "Mystery", "Action", "Horror", "Drama"],
    "Romance":      ["Drama", "Comedy", "Family", "Music"],
    "Animation":    ["Comedy", "Family", "Adventure", "Fantasy"],
    "Crime":        ["Thriller", "Mystery", "Drama", "Action"],
    "Adventure":    ["Action", "Fantasy", "Sci-Fi", "Animation", "Family"],
    "Fantasy":      ["Adventure", "Animation", "Sci-Fi", "Action"],
    "Mystery":      ["Thriller", "Crime", "Horror", "Drama"],
    "Biography":    ["Documentary", "History", "Drama"],
    "History":      ["Documentary", "Biography", "Drama", "War"],
    "War":          ["History", "Action", "Drama", "Thriller"],
    "Music":        ["Documentary", "Drama", "Romance", "Comedy"],
    "Sport":        ["Documentary", "Drama", "Action"],
    "Western":      ["Action", "Adventure", "Drama", "History"],
    "Family":       ["Animation", "Comedy", "Adventure"],
    "Kids":         ["Animation", "Family", "Comedy"],
    # Streaming-era / niche genres — without these, adjacent pool is always empty
    "Anime":        ["Animation", "Action", "Fantasy", "Sci-Fi", "Adventure"],
    "TV Movie":     ["Drama", "Comedy", "Romance", "Action", "Thriller"],
    "Reality":      ["Documentary", "Comedy", "Drama", "Sport"],
    "Talk":         ["Documentary", "News", "Comedy"],
    "News":         ["Documentary", "History", "Crime"],
}

# ---------------------------------------------------------------------------
# Tone guard — tonal-identity genres block emotionally-incompatible adjacents
# ---------------------------------------------------------------------------
# Maps genres with a strong tonal identity to the tone value(s) that
# adjacent/wildcard candidates MUST NOT carry.  Only "light" and "dark" can
# be blocked — "neutral" always passes through.
#
# Conflict rule: when selected genres span both ends of the tonal spectrum
# (e.g. Horror+Comedy → one blocks "light", the other blocks "dark")
# the guard is disabled entirely rather than over-restricting the pool.
GENRE_TONE_GUARDS: dict[str, frozenset] = {
    # Dark-identity genres — adjacent/wildcard must NOT be light
    "Horror":    frozenset({"light"}),
    "War":       frozenset({"light"}),
    "Thriller":  frozenset({"light"}),
    "Crime":     frozenset({"light"}),
    # Light-identity genres — adjacent/wildcard must NOT be dark
    "Comedy":    frozenset({"dark"}),
    "Romance":   frozenset({"dark"}),
    "Family":    frozenset({"dark"}),
    "Kids":      frozenset({"dark"}),
    "Animation": frozenset({"dark"}),
    "Music":     frozenset({"dark"}),
}

# ---------------------------------------------------------------------------
# Tone-group classification (Task #10)
# ---------------------------------------------------------------------------
# A candidate's *effective* tone group is derived from its content card tone
# PLUS strong thematic / audience signals.  This catches cases the raw
# card.tone misses: a feel-good Christmas comedy reads as "light" even when its
# raw tone landed on "neutral", and a war drama reads as "dark" regardless of
# how its raw tone was classified.  These groups feed the adjacent/wildcard
# tone gate so exploration stays emotionally related to the selected genre.
LIGHT_TONE_THEMES = frozenset({
    "feel-good", "holiday", "family-drama", "musical", "nostalgic",
})
DARK_TONE_THEMES = frozenset({
    "graphic-violence", "serial-killer", "slasher", "war-drama", "gangster",
    "mafia", "psychological-horror", "dread", "revenge", "prison-drama",
    "true-crime",
})

# Recognised documentary subtype themes — used for Documentary subtype/tone
# continuity so a Documentary feed's exploration stays within coherent doc
# subtypes rather than serving emotionally random documentaries.
DOC_SUBTYPE_THEMES = frozenset({
    "history-doc", "nature-doc", "music-doc", "sports-doc", "food-doc",
    "true-crime", "biographical",
})


def _candidate_tone_group(movie: dict) -> str:
    """Classify a candidate into a coarse tone group: 'light' | 'dark' | 'neutral'.

    Strong thematic signals win over the raw card.tone so emotionally loud
    titles are grouped correctly even when their heuristic tone is neutral.
    Dark themes take precedence over light ones (safer to treat a mixed title
    as dark when gating a light feed).
    """
    card   = movie.get("card") or {}
    themes = set(card.get("themes") or movie.get("themes") or [])
    if themes & DARK_TONE_THEMES:
        return "dark"
    if themes & LIGHT_TONE_THEMES:
        return "light"
    tone = card.get("tone", "neutral")
    if tone in ("light", "dark"):
        return tone
    if card.get("audience_type") in ("kids", "family"):
        return "light"
    return "neutral"


def _behavior_supports_tone(user: dict, tone_group: str) -> bool:
    """True when the user's learned signals show genuine appetite for
    `tone_group`, so the tone guard should relax for it.

    Spec (Task #10): incompatible tones are blocked "unless the user's
    behavior explicitly supports it".  Appetite is read from learned
    tone_weights (the tone the user keeps saving) and theme_weights (positive
    weight on themes belonging to that tone group).
    """
    tw = effective_weight_map(user, "tone_weights")
    if float(tw.get(tone_group, 0)) >= 2.0:
        return True
    theme_w = effective_weight_map(user, "theme_weights")
    probe = LIGHT_TONE_THEMES if tone_group == "light" else DARK_TONE_THEMES
    return any(float(theme_w.get(t, 0)) >= 2.0 for t in probe)


# ---------------------------------------------------------------------------
# Reality-TV / exploration-quality / provider-confidence helpers
# ---------------------------------------------------------------------------

def _is_reality(movie: dict) -> bool:
    """True if a title is reality TV / dating / celebrity / game-show content.

    Detected by genre (Reality/Talk) or by an explicit keyword backstop on the
    title/overview so dating & celebrity formats that were tagged with only a
    co-genre (e.g. Comedy) are still caught.
    """
    if set(movie.get("genres") or []) & REALITY_GENRES:
        return True
    text = f"{movie.get('title', '')} {movie.get('overview', '')}".lower()
    return any(k in text for k in REALITY_KEYWORDS)


def _reality_allowed(user: dict) -> bool:
    """True when reality content should be allowed for this user — either they
    explicitly selected a reality genre at onboarding or their learned genre
    weight shows they repeatedly like it."""
    if set(user.get("genres") or []) & REALITY_GENRES:
        return True
    gw = effective_weight_map(user, "genre_weights")
    return any(float(gw.get(g, 0)) >= REALITY_LIKE_THRESHOLD for g in REALITY_GENRES)


def _explore_quality_ok(movie: dict) -> bool:
    """Quality floor for adjacent/wildcard candidates so low-vote niche filler
    never dominates the broadening pool.  Core titles bypass this entirely."""
    vc  = int(movie.get("vote_count") or 0)
    rt  = float(movie.get("rating") or 0)
    pop = float(movie.get("popularity") or 0)
    return (
        vc >= EXPLORE_VOTE_FLOOR
        or rt >= EXPLORE_RATING_FLOOR
        or pop >= EXPLORE_POPULARITY_FLOOR
    )


def _provider_confidence(movie: dict, subs: set, user_region: str) -> str:
    """Classify how confident we are the user can actually watch this title.

      high   — streaming on one of the user's subscriptions (or, when no subs
               are set, streaming on any service) in their region
      medium — streaming on another service, or rent/buy only
      low    — no provider data, or provider data for a different region
    """
    from providers_util import resolve_region_providers
    resolved = resolve_region_providers(movie, user_region)
    if user_region and not resolved["region_matched"]:
        return "low"
    avail = set(resolved["available_on"])
    rent  = set(resolved["rent_on"])
    buy   = set(resolved["buy_on"])
    if subs:
        if avail & subs:
            return "high"
        if avail:
            return "medium"
        if rent or buy:
            return "medium"
        return "low"
    if avail:
        return "high"
    if rent or buy:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _genre_vector(weights: dict) -> dict:
    """Return a normalized genre weight dict (sum to 1)."""
    if not weights:
        return {}
    total = sum(abs(v) for v in weights.values()) or 1.0
    return {g: v / total for g, v in weights.items()}


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _maturity(user: dict) -> float:
    """0..1 — how 'mature' is this user's positive preference signal?

    Governs quality-vs-personalisation balance and onboarding decay.
    Reaches 1.0 at ~40 interactions — fast enough to feel personal, but slow
    enough that the engine doesn't overfit and strip out recognisable titles by
    swipe ~25 (the old curve saturated too quickly).
    """
    interactions = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    return min(1.0, interactions / 40.0)


def _neg_maturity(user: dict) -> float:
    """0..1 — how strongly should learned *negative* signals apply?

    Negative signals (language/decade aversions built from skips) must kick in
    much faster than positive ones — a user repeatedly skipping Japanese films
    should see the effect after ~5 skips, not 25.  Reaches 1.0 at 12 interactions.
    A floor of 0.20 ensures even brand-new users get a minimal suppression effect
    if they skip the same thing several times in a row.
    """
    interactions = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    return max(0.20, min(1.0, interactions / 12.0))


def _confidence_tier(user: dict) -> str:
    """Human-readable personalisation confidence tier.

    Tiers drive different engine behaviours:
      exploratory      (< 20 interactions): popularity-dominant, wide variety
      semi_confident   (20–49):             behavioural signals taking over
      confident        (50–99):             strong personalisation active
      strongly_personalised (100+):         full signal strength, minimal exploration
    """
    n = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    if n < 20:   return "exploratory"
    if n < 50:   return "semi_confident"
    if n < 100:  return "confident"
    return "strongly_personalised"


def _recently_shown_active(user: dict) -> set:
    """Ids shown in the last RECENTLY_SHOWN_COOLDOWN_HRS hours."""
    rs = user.get("recently_shown") or []
    if not rs:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENTLY_SHOWN_COOLDOWN_HRS)
    out = set()
    for entry in rs:
        ts = entry.get("at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts and ts >= cutoff:
            mid = entry.get("id")
            if mid:
                out.add(mid)
    return out


async def _eligible_skip_reintros(user: dict, top_genres: set) -> set:
    """Old skips (>30d) where movie's genres overlap user's currently boosted
    genres become eligible to be re-introduced — taste shifts happen."""
    if not top_genres:
        return set()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=SKIP_COOLDOWN_DAYS)).isoformat()
    cursor = db.user_actions.find(
        {"user_id": user["user_id"], "action": "skip", "created_at": {"$lt": cutoff_iso}},
        {"_id": 0, "movie_id": 1},
    )
    rows = await cursor.to_list(length=1000)
    skip_ids = {r["movie_id"] for r in rows}
    if not skip_ids:
        return set()
    # ── Skip intelligence (Task #23 Step 8) ──────────────────────────────────
    # HARD skips — onboarding dislikes and repeated rejections — never become
    # reintro-eligible. They can still appear via the last-resort pool floor
    # when the catalogue is too thin to fill the feed any other way, so this is
    # a soft de-prioritisation of the *reintro* path, not a hard pool filter.
    hard_skips = set(user.get("hard_skips") or [])
    skip_ids -= hard_skips
    if not skip_ids:
        return set()
    catalog_by_id = {m["id"]: m for m in get_catalog()}
    return {
        mid for mid in skip_ids
        if mid in catalog_by_id and (set(catalog_by_id[mid].get("genres") or []) & top_genres)
    }


def _session_genre_fatigue(
    user: dict,
    recent_n: int = 15,
    *,
    exclude_genres: "set | frozenset" = frozenset(),
) -> dict[str, float]:
    """Repetition prevention: penalise genres dominating the last N shown cards.

    If a genre makes up >35% of the recent feed, it receives a negative score
    adjustment proportional to how much it exceeds that threshold.  This stops
    the engine locking onto a single genre even when learned weights strongly
    prefer it — e.g. after 10 consecutive Thriller cards, Thrillers are nudged
    down so the next page feels fresh.

    `exclude_genres` — genres that must NEVER be penalised regardless of frequency.
    When the user explicitly selected Documentary at onboarding, Documentary
    fatigue must not kick in and suppress the very content they asked for.

    Penalties are capped at -2.0 per genre so items are *nudged*, never blocked.
    Returns: {genre: penalty_float}  (all values ≤ 0).
    """
    rs = user.get("recently_shown") or []
    if len(rs) < 5:
        return {}

    recent_ids = [e.get("id") for e in rs[:recent_n] if e.get("id")]
    if not recent_ids:
        return {}

    catalog_by_id = {m["id"]: m for m in get_catalog()}
    genre_counts: Counter = Counter()
    seen_count = 0
    for mid in recent_ids:
        m = catalog_by_id.get(mid)
        if m:
            for g in (m.get("genres") or []):
                genre_counts[g] += 1
            seen_count += 1

    if seen_count == 0:
        return {}

    FATIGUE_THRESHOLD = 0.35   # genre must exceed 35% of recent cards to trigger
    MAX_PENALTY       = -2.0   # maximum per-genre nudge
    penalties: dict[str, float] = {}
    for g, count in genre_counts.items():
        if g in exclude_genres:
            continue          # never fatigue a genre the user explicitly selected
        frac = count / seen_count
        if frac > FATIGUE_THRESHOLD:
            # Linear from 0 at threshold to MAX_PENALTY at 2× threshold
            intensity = min(1.0, (frac - FATIGUE_THRESHOLD) / FATIGUE_THRESHOLD)
            penalties[g] = round(intensity * MAX_PENALTY, 3)
    return penalties


async def _collaborative_boost_set(user: dict, top_n: int = COLLAB_NEIGHBOURS) -> set:
    """Find users with the most similar genre_weights and gather titles they
    saved. Returns a set of movie_ids that should get a soft boost."""
    my_vec = _genre_vector(effective_weight_map(user, "genre_weights"))
    if not my_vec:
        return set()
    # Sample candidate neighbours: users with at least one saved title and a
    # non-empty genre_weights map. We cap at 200 candidates to keep it cheap.
    cursor = db.users.find(
        {
            "user_id": {"$ne": user["user_id"]},
            "saved.0": {"$exists": True},
            "genre_weights": {"$exists": True, "$ne": {}},
        },
        {"_id": 0, "user_id": 1, "saved": 1, "genre_weights": 1},
    ).limit(200)
    candidates = await cursor.to_list(length=200)
    scored = []
    for u in candidates:
        sim = _cosine(my_vec, _genre_vector(u.get("genre_weights") or {}))
        if sim > 0.2:
            scored.append((sim, u))
    scored.sort(key=lambda x: x[0], reverse=True)
    boost_ids: set = set()
    for sim, u in scored[:top_n]:
        for mid in u.get("saved") or []:
            boost_ids.add(mid)
    return boost_ids


def _pref_confidence(weight: float) -> float:
    """Evidence-driven confidence multiplier for a single learned preference.

    A preference exerts influence in proportion to the evidence behind it, using
    the spec's bands of net positive likes:

        high   ≈ 50+ likes  → 1.00  (drives ranking)
        medium ≈ 10  likes  → 0.80
        low    ≈ 2   likes  → 0.55  (gentle nudge)
        below            → 0.35  (barely-evidenced — only the faintest hint)

    Net weight is a faithful proxy for evidence: each like adds ~+1…+3 and each
    skip subtracts, so the accumulated magnitude tracks how much the user has
    actually shown us.  Negative weights (aversions) keep the full multiplier so
    dislikes still register quickly.
    """
    if weight < 0:
        return 1.0
    if weight >= 50:
        return 1.0
    if weight >= 10:
        return 0.80
    if weight >= 2:
        return 0.55
    return 0.35


def _hybrid_score(
    movie: dict,
    user: dict,
    *,
    maturity: float,
    neg_maturity: float,
    collab_set: set,
    learned_top_genres: set,
    current_year: int,
    extra_genre_boost: "dict | None" = None,
    genre_fatigue: "dict | None" = None,
    community_cache: "dict[str, float] | None" = None,
) -> float:
    """Hybrid score blending quality, explicit prefs, learned weights, collab,
    freshness, mood/tone, pacing, theme affinity, and session-fatigue.

    Design pillars
    ──────────────
    confidence weighting   — low-metadata titles (no keywords/overview) are
                             gently downweighted; [0.80, 1.00] multiplier on
                             the quality term so they're nudged, never blocked.
    onboarding overlap     — binary match (not N× per genre), decays with maturity.
    learned genre weights  — tanh(w/6) gives natural diminishing returns;
                             a single save cannot dominate the feed.
    tone / pacing / theme  — three new maturity-gated personalisation axes
                             learned from every swipe and engagement event.
    graduated freshness    — 0.70 / 0.40 / 0.15 stepped curve plus a distinct
                             evergreen-classic bonus (≥8.2 rating + ≥3 000 votes)
                             so beloved older titles aren't buried.
    session genre fatigue  — negative nudge for genres overrepresented in the
                             last 15 shown cards; prevents single-genre ruts.
    documentary boost      — explicit popularity-compensation (TMDB pop 2–20
                             vs 100–500 for blockbusters); decays with maturity.
    """
    rating     = float(movie.get("rating") or 7.0)
    popularity = float(movie.get("popularity") or 0)

    # ── Quality: popularity → cold-start, rating → mature ───────────────────
    # Popularity keeps a small PERMANENT floor (0.12) so recognisable, widely
    # watched titles never fully vanish once a user matures — this stops the feed
    # lurching into obscure/niche territory once personalisation kicks in.
    pop_term    = math.log1p(popularity) * max(0.12, 1.0 - maturity)
    rating_term = (rating / 2.0) * (0.5 + 0.5 * maturity)
    quality     = pop_term + rating_term

    # ── Confidence weighting (NEW) ───────────────────────────────────────────
    # Titles with sparse metadata (no keywords, no overview) get a gentle
    # downweight: conf_score ∈ [0,1] → multiplier ∈ [0.80, 1.00].
    card = movie.get("card") or {}
    conf = float(card.get("confidence_score") or 0.5)
    quality *= 0.80 + 0.20 * conf

    # Demote very low-vote titles so obscure entries never out-rank recognisable
    # ones. Strongest at cold-start, but a mild penalty persists at all maturities
    # (soft scoring only — the title stays in the candidate pool).
    _vc = movie.get("vote_count") or 0
    if _vc < 50:
        quality -= 0.5 if maturity < 0.4 else 0.25
    elif _vc < 150:
        quality -= 0.1

    mg = set(movie.get("genres") or [])

    # ── Explicit onboarding prefs ────────────────────────────────────────────
    onboard_prefs = set(user.get("genres") or [])
    onboard_match = 1 if (mg & onboard_prefs) else 0

    # ── Learned genre weights (tanh-normalised, confidence-scaled) ───────────
    # tanh(w/6) normalises magnitude: w=1→0.165, w=3→0.46, w=6→0.76, w=12→0.96.
    # _pref_confidence then scales each genre's contribution by how much evidence
    # backs it (high ≈50+ likes drive ranking; low ≈2 likes only nudge), so a
    # thinly-evidenced genre cannot punch above a well-established preference.
    gw = effective_weight_map(user, "genre_weights")
    learned = sum(
        math.tanh(gw.get(g, 0) / 6.0) * _pref_confidence(gw.get(g, 0)) for g in mg
    )
    if extra_genre_boost:
        learned += sum(extra_genre_boost.get(g, 0) for g in mg)

    # ── Feeling-emphasis ramp ──────────────────────────────────────────────────
    # As the engine learns a user, *how a title feels* — mood/tone, pacing, and
    # the themes that encode tension and character archetypes — should drive
    # ranking more than the raw genre label.  This multiplier lifts the POSITIVE
    # tone/pacing/theme contributions from 1.0× at cold-start to ~1.6× once the
    # user is well understood, so by ~100 swipes the feed tracks taste over genre.
    feeling_emphasis = 1.0 + 0.6 * maturity

    # Onboarding title feedback is explicit, not an impression. The standard
    # maturity gate would hide its non-genre evidence in a brand-new feed, so
    # grant up to 0.60 score confidence after ten deliberate training answers.
    # Its separate source maps still decay against later genuine interactions.
    has_onboarding_source = any(
        bool(user.get(f"onboarding_{field}"))
        for field in (
            "genre_weights", "type_weights", "tone_weights", "pacing_weights",
            "theme_weights", "language_weights", "decade_weights", "cast_weights",
            "director_weights", "writer_weights", "runtime_weights",
            "popularity_weights", "quality_pref_weights",
        )
    )
    signal_maturity = max(
        maturity,
        min(0.60, 0.60 * len(user.get("onboarding_rated") or []) / 10.0),
    ) if has_onboarding_source else maturity

    # ── Source-only onboarding metadata affinity ─────────────────────────────
    # These are bounded soft re-rank terms, never candidate-pool conditions.
    # Existing users have no onboarding_* maps, so this adds exactly zero for
    # them.  Cast's old generic-map contribution remains feature-flagged below;
    # explicit onboarding cast evidence is intentionally safe to use from day
    # one because it is capped and has the same post-onboarding decay as every
    # other title-training dimension.
    def _source_people(field: str, names: list, cap: float) -> float:
        weights = onboarding_weight_map(user, field)
        if not weights or not names:
            return 0.0
        affinity = sum(
            math.tanh(weights.get(person_key(name), 0.0) / 3.0)
            for name in names
        )
        return max(-cap, min(cap, affinity)) * signal_maturity

    _onboard_cast = _source_people(
        "cast_weights", (card.get("cast") or movie.get("cast_names") or [])[:3], 1.10
    )
    _onboard_director = _source_people(
        "director_weights", (movie.get("director_names") or [])[:2], 0.70
    )
    _onboard_writer = _source_people(
        "writer_weights", (movie.get("writer_names") or [])[:2], 0.55
    )

    runtime = movie.get("runtime") or movie.get("total_runtime") or 0
    runtime_bucket = "short" if runtime and runtime < 95 else ("long" if runtime and runtime > 125 else "medium")
    runtime_weight = onboarding_weight_map(user, "runtime_weights").get(runtime_bucket, 0.0)
    runtime_term = math.tanh(runtime_weight / 3.0) * 0.45 * signal_maturity

    popularity = float(movie.get("popularity") or 0)
    popularity_bucket = "niche" if popularity < 10 else ("popular" if popularity > 50 else "moderate")
    popularity_weight = onboarding_weight_map(user, "popularity_weights").get(popularity_bucket, 0.0)
    popularity_term = math.tanh(popularity_weight / 3.0) * 0.35 * signal_maturity

    quality_tier = card.get("quality_tier")
    quality_weight = onboarding_weight_map(user, "quality_pref_weights").get(quality_tier, 0.0)
    quality_affinity_term = math.tanh(quality_weight / 3.0) * 0.35 * signal_maturity

    # ── Mood / tone preference ────────────────────────────────────────────────
    # Uses neg_maturity for negative weights (aversions respond faster than
    # positive preferences).  tanh(w/3): 1→0.32, 3→0.76, 5→0.99, ×2.5 → max 2.5,
    # then lifted by feeling_emphasis as positive taste matures.
    tone_weights = effective_weight_map(user, "tone_weights")
    card_tone    = card.get("tone", "neutral")
    _tw_raw = tone_weights.get(card_tone, 0)
    _tone_mat  = neg_maturity if _tw_raw < 0 else signal_maturity
    _tone_emph = feeling_emphasis if _tw_raw >= 0 else 1.0
    tone_score = math.tanh(_tw_raw / 3.0) * 2.5 * _tone_mat * _tone_emph

    # ── Pacing preference ─────────────────────────────────────────────────────
    # Pacing (slow-burn vs propulsive) is a core "feel" axis; it ramps with
    # feeling_emphasis like tone/theme and carries a touch more base weight now.
    pacing_weights = effective_weight_map(user, "pacing_weights")
    card_pacing    = card.get("pacing", "medium")
    _pw_raw        = pacing_weights.get(card_pacing, 0)
    _pace_emph     = feeling_emphasis if _pw_raw >= 0 else 1.0
    pacing_score   = math.tanh(_pw_raw / 4.0) * 1.1 * signal_maturity * _pace_emph

    # ── Theme affinity (tension + character archetypes live here) ──────────────
    # Themes carry BOTH positive and negative signal (Task #8). Disliked themes
    # suppress candidates; positive themes boost.  Negatives use neg_maturity so
    # aversions kick in fast (~5 skips); positives ramp with maturity AND the
    # feeling_emphasis lift.  Themes encode the "same feeling" signals the genre
    # label misses — tension (suspense, psychological, survival) and character
    # archetypes (found-family, redemption, coming-of-age) — so they are the main
    # lever for "understands me, not trapped in one genre".
    theme_weights = effective_weight_map(user, "theme_weights")
    card_themes   = set(card.get("themes") or [])
    pos_theme = 0.0
    neg_theme = 0.0
    for t in card_themes:
        w = theme_weights.get(t, 0)
        if w > 0:
            pos_theme += math.tanh(w / 3.0)
        elif w < 0:
            neg_theme += math.tanh(w / 3.0)   # tanh of negative is negative
    theme_score = (
        min(2.5, pos_theme) * 1.2 * signal_maturity * feeling_emphasis
        + max(-3.0, neg_theme) * 1.5 * neg_maturity
    )

    # ── Language affinity / aversion ─────────────────────────────────────────
    # Uses neg_maturity (floor 0.20) so skips suppress fast:
    #   5 skips  @ 8 total  → weight −4.0 → lang_score ≈ −3.2  (noticeable)
    #   10 skips @ 15 total → weight −8.0 → lang_score ≈ −5.0  (near suppression)
    #   10+ skips           → auto_blocked hard filter removes from pool entirely
    # tanh(w/2): denominator tightened so effect is felt sooner.
    lang_weights = effective_weight_map(user, "language_weights")
    movie_lang   = movie.get("original_language") or "en"
    _lw_raw  = lang_weights.get(movie_lang, 0)
    _lang_mat = neg_maturity if _lw_raw < 0 else signal_maturity
    lang_score = math.tanh(_lw_raw / 2.0) * 5.0 * _lang_mat

    # ── English-language prior (UK-first) ─────────────────────────────────────
    # WatchSmart is UK-first. This fixes two real problems seen in production:
    #  1. SKIP-POISON on the dominant language. A skip is the default reject
    #     action, so a heavy skipper in an English-dominant catalogue drives
    #     their OWN English weight strongly negative (e.g. −56) purely from skip
    #     volume — not because they dislike English. That noise was suppressing
    #     English titles BELOW foreign ones (whose weight was less negative),
    #     letting Japanese & other foreign content float to the top. We therefore
    #     never let English go net-negative from learned weight, mirroring the
    #     dominance protection the hard auto-block already applies.
    #  2. Foreign titles should only surface once the user shows genuine appetite.
    # The whole effect decays to ~0 the moment the user positively rates ANY
    # foreign language, so real foreign fans are unaffected. Soft re-rank only —
    # it never filters, so the candidate pool is untouched.
    _foreign_appetite = max(
        [w for _l, w in lang_weights.items() if _l != "en" and w > 0] + [0.0]
    )
    _eng_prior = max(0.0, 1.0 - math.tanh(_foreign_appetite / 3.0))
    if movie_lang == "en":
        # Baseline language: protect from skip-volume noise, then nudge up.
        lang_score = max(lang_score, 0.0) + 1.5 * _eng_prior
    elif _lw_raw <= 0:
        # Foreign with no positive signal: decisive UK-first demotion.
        lang_score -= 2.5 * _eng_prior

    # ── Decade preference ─────────────────────────────────────────────────────
    # Same neg_maturity acceleration for aversions:
    #   5 decade-skips @ 8 total → weight −3.2 → decade_score ≈ −2.5
    #   8+ skips                 → auto_blocked hard filter removes from pool
    decade_weights = effective_weight_map(user, "decade_weights")
    _m_year        = movie.get("year") or 0
    movie_decade   = f"{(_m_year // 10) * 10}s" if _m_year else "2000s"
    _dw_raw  = decade_weights.get(movie_decade, 0)
    _decade_mat = neg_maturity if _dw_raw < 0 else signal_maturity
    decade_score = math.tanh(_dw_raw / 2.0) * 3.5 * _decade_mat * _pref_confidence(_dw_raw)

    # ── Provider affinity ────────────────────────────────────────────────────
    provider_bonus = 1.8 if set(movie.get("available_on") or []) & set(user.get("subscriptions") or []) else 0.0

    # ── Type preference ──────────────────────────────────────────────────────
    type_pref_raw = effective_weight_map(user, "type_weights").get(movie.get("type"), 0)
    type_pref     = math.tanh(type_pref_raw / 6.0)

    # ── Graduated freshness (IMPROVED from binary) ───────────────────────────
    # Four tiers instead of the old binary ≤2y→0.6 / else→0:
    #   ≤1y  : 0.70 — brand new
    #   ≤3y  : 0.40 — recently released
    #   ≤6y  : 0.15 — still fairly current
    #   older: 0.00 — no freshness boost  …except beloved classics:
    #   ≥8.2 rating + ≥3 000 votes → 0.20 evergreen bonus so Shawshank /
    #   Dark Knight aren't buried once maturity shifts toward personalisation.
    year      = movie.get("year") or 0
    age_years = max(0, current_year - year) if year else 999
    if age_years <= 1:
        freshness = 0.70
    elif age_years <= 3:
        freshness = 0.40
    elif age_years <= 6:
        freshness = 0.15
    elif (movie.get("rating") or 0) >= 8.2 and (movie.get("vote_count") or 0) >= 3000:
        freshness = 0.20   # evergreen classic bonus
    else:
        freshness = 0.0

    # ── Soft age penalty (Task #35) ────────────────────────────────────────
    # After eligibility, older titles that DO get into the pool must be
    # genuinely excellent to rank high. Graduated penalty — never blocks,
    # only soft-re-ranks within the already-eligible pool. Exception-eligible
    # classics get partial relief via the evergreen freshness bonus above.
    age_penalty = 0.0
    if year and year < 2005:
        age_penalty = 0.6  # strong penalty for pre-2005
    elif year and year < 2010:
        age_penalty = 0.2  # moderate penalty for 2005–2009
    # Penalty is reduced for very high quality (rating 8.0+ with 1000+ votes)
    if (movie.get("rating") or 0) >= 8.0 and (movie.get("vote_count") or 0) >= 1000:
        age_penalty *= 0.3

    # ── Collaborative bonus ──────────────────────────────────────────────────
    collab = COLLAB_BONUS if movie["id"] in collab_set else 0

    # ── Re-intro bonus ───────────────────────────────────────────────────────
    reintro = 0.5 if (mg & learned_top_genres) else 0

    jitter = (hash(movie["id"]) % 100) / 1000.0

    # ── Onboarding genre signal (contradiction-aware persistence) ────────────
    # Onboarding is a LONG-TERM taste signal, not a short-term session signal: it
    # must stay influential many sessions later and erode ONLY when later
    # behaviour contradicts the specific onboarding genre — never by the mere
    # passage of swipes/sessions.  For the onboarding genre(s) this title carries
    # we read the user's *learned* net genre weight as the behavioural evidence:
    #   weight ≥ 0 (or simply unseen) → uncontradicted → keep onboarding at full
    #     strength regardless of how many swipes have happened.
    #   weight  < 0 → the user has repeatedly rejected that genre → fade toward a
    #     low floor in proportion to how strongly they contradicted it.
    # Using the MAX matched weight means a title that also carries an
    # uncontradicted onboarding genre keeps the bonus even if one matched genre
    # was rejected.  Pure scoring lever — pool membership is untouched.
    interactions = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    matched_onboard = mg & onboard_prefs
    if matched_onboard:
        _ow = max(gw.get(g, 0.0) for g in matched_onboard)
        if _ow >= 0:
            _onboard_decay = 1.0
        else:
            _contra = min(1.0, -_ow / 6.0)        # ≈ −6 net weight ⇒ fully contradicted
            _onboard_decay = max(0.15, 1.0 - 0.85 * _contra)
    else:
        _onboard_decay = 0.0
    genre_pref_bonus = onboard_match * 6.0 * _onboard_decay
    # ── Cold-start intent dominance (first ~50 swipes) ───────────────────────
    # A brand-new UK user's chosen genres must clearly out-rank generic-popular
    # titles that only carry a selected genre incidentally.  The trap: Drama (the
    # catalogue's biggest genre) is the universal co-tag on Crime/Action/Thriller
    # titles, so rewarding co-tag COUNT just surfaces more Drama.  Instead reward
    # a selected genre being the title's PRIMARY tag — what it most "reads as" —
    # so the feed FEELS like the user's picks, not their picks' co-tag.  Pure
    # scoring lever (no pool filtering); decays to 0 by ~50 interactions, after
    # which learned behaviour takes over with NO genre lock-in (matured scoring
    # is byte-identical to before).
    if onboard_match and interactions < 50:
        _coldstart   = (50 - interactions) / 50.0        # 1.0 → 0.0 over 50 swipes
        _glist       = movie.get("genres") or []
        _primary_hit = bool(_glist) and _glist[0] in onboard_prefs
        _w           = 1.6 if _primary_hit else 0.5      # primary-led ≫ co-tag only
        genre_pref_bonus += 6.0 * _onboard_decay * _coldstart * _w

    # ── Niche genre popularity-compensation boosts ───────────────────────────
    # Several genres score 2–30 TMDB popularity vs 100–500 for blockbusters.
    # Without per-genre boosts they are buried in mixed-genre or co-selection
    # feeds (e.g. Horror + Thriller → Thrillers dominate; Documentary + Crime
    # → Crime thrillers dominate).  Boosts decay with maturity so that learned
    # signals take over naturally once the user has real interaction history.
    niche_boost = 0.0
    for _ng, (_ob, _lb) in NICHE_GENRE_BOOSTS.items():
        if _ng in mg:
            if _ng in onboard_prefs:
                niche_boost += _ob * max(0.4, 1.0 - 0.6 * maturity)
            elif gw.get(_ng, 0) > 0:
                niche_boost += _lb
    niche_boost = min(niche_boost, 8.0)  # cap against double-genre stacking
    doc_boost = niche_boost  # backward-compat alias

    # ── Session genre fatigue (NEW) ──────────────────────────────────────────
    # Gently disfavours genres overrepresented in the last 15 shown cards.
    # All penalties are ≤ 0; total is floored at -2.0 per call.
    fatigue = 0.0
    if genre_fatigue:
        for g in mg:
            fatigue += genre_fatigue.get(g, 0.0)
        fatigue = max(-2.0, fatigue)

    # ── Catalogue-quality blend (Task #23) ───────────────────────────────────
    # Soft nudge from the 0-100 card quality score, centred at ~Tier B so an
    # average title nets ≈0, strong (A) titles rise and weak (D) titles fall.
    # The weakest tier gets an extra demotion. NEVER a pool filter; missing
    # scores get the benefit of the doubt (treated as a healthy Tier-B 60).
    q_score = card.get("quality_score")
    q_score = 60 if q_score is None else int(q_score)
    quality_term = (q_score / 100.0 - QUALITY_PIVOT) * QUALITY_WEIGHT
    if card.get("quality_tier") == "D":
        quality_term -= QUALITY_TIER_D_PENALTY

    # ── Actor affinity ───────────────────────────────────────────────────────
    # Learned from saves/likes (cast_weights on the user). Gentle, maturity-
    # gated, and capped so a single favourite face can't dominate the feed.
    cast_term = 0.0
    cast_weights = user.get("cast_weights") or {}
    if cast_weights:
        _cast = card.get("cast") or movie.get("cast_names") or []
        _ca = sum(
            math.tanh(_w / 3.0)
            for c in _cast[:5]
            if isinstance((_w := cast_weights.get(person_key(c), 0)), (int, float))
        )
        cast_term = max(-CAST_AFFINITY_WEIGHT, min(CAST_AFFINITY_WEIGHT, _ca)) * maturity

    # ── Community quality signal (Task #38) ─────────────────────────────────
    # Soft re-rank nudge only.  Passed per-request to avoid cross-request
    # contamination under concurrent feed builds.
    community_term = 0.0
    if community_cache is not None:
        cqs = community_cache.get(movie.get("id"))
        if cqs is not None:
            # Mature users (>50 interactions) get a tiny community nudge;
            # semi-confident users (20-49) get a modest one.
            _comm_weight = 0.08 if maturity >= 0.5 else 0.15
            community_term = cqs * _comm_weight

    return (
        quality
        + quality_term
        + cast_term
        + _onboard_cast
        + _onboard_director
        + _onboard_writer
        + runtime_term
        + popularity_term
        + quality_affinity_term
        + genre_pref_bonus
        + learned * 2.3 * (0.65 + 0.25 * maturity)   # genre influence flattened so feeling can overtake it
        + lang_score
        + decade_score
        + type_pref * 0.8
        + tone_score
        + pacing_score
        + theme_score
        + freshness
        + collab
        + reintro
        + provider_bonus
        + doc_boost
        + fatigue
        + community_term
        - age_penalty
        + jitter
    )


# Human-readable labels for content card themes used in reason strings
_THEME_LABELS: dict[str, str] = {
    "true-crime":        "true crime",
    "psychological":     "psychological thriller",
    "moral-grey":        "morally complex",
    "mind-bending":      "mind-bending",
    "biographical":      "biographical",
    "coming-of-age":     "coming-of-age",
    "espionage":         "spy thriller",
    "heist":             "heist",
    "survival":          "survival",
    "high-fantasy":      "epic fantasy",
    "war-drama":         "war drama",
    "feel-good":         "feel-good",
    "found-family":      "found-family",
    "dystopian":         "dystopian",
    "post-apocalyptic":  "post-apocalyptic",
    "space-opera":       "space opera",
    "redemption":        "redemption story",
    "dark-comedy":       "dark comedy",
    "romance":           "romance",
    "literary-adaptation": "literary adaptation",
    "limited-series":    "limited series",
    "suspense":          "suspense",
    "drama-heavy":       "character-driven drama",
    "prison-drama":      "prison drama",
    "courtroom":         "courtroom drama",
    "medical-drama":     "medical drama",
}


def _taste_profile(user: dict) -> dict:
    """Build a lightweight taste fingerprint from the user's saved/watched history.

    Reads the last 25 titles the user saved or watched and extracts:
      - top_tones:    dominant tones ("dark", "light") they gravitate toward
      - top_themes:   recurring themes (true-crime, psychological, etc.)
      - top_genres:   most boosted genres by learned weight
      - runtime_pref: "short" (<92 min) / "medium" / "long" (>128 min)
      - niche_leaning: True if average popularity of saved/watched < 18
      - history_size: number of saved+watched titles considered
    """
    catalog_by_id = {m["id"]: m for m in get_catalog()}

    saved_ids   = list(user.get("saved") or [])
    watched_ids = list(user.get("watched") or [])
    history_ids = (saved_ids + watched_ids)[-25:]

    tones: dict[str, int]  = {}
    themes: dict[str, int] = {}
    runtimes: list[float]  = []
    popularities: list[float] = []

    for mid in history_ids:
        m = catalog_by_id.get(mid)
        if not m:
            continue
        card = m.get("card") or {}
        tone = card.get("tone")
        if tone:
            tones[tone] = tones.get(tone, 0) + 1
        for t in (card.get("themes") or []):
            themes[t] = themes.get(t, 0) + 1
        rt = m.get("runtime") or 0
        if rt > 0:
            runtimes.append(rt)
        pop = m.get("popularity") or 0
        if pop > 0:
            popularities.append(pop)

    top_tones  = [t for t, _ in sorted(tones.items(),  key=lambda x: x[1], reverse=True)[:2]]
    top_themes = [t for t, _ in sorted(themes.items(), key=lambda x: x[1], reverse=True)[:5]]

    gw = user.get("genre_weights") or {}
    top_genres = [g for g, v in sorted(gw.items(), key=lambda x: x[1], reverse=True)[:4] if v > 0]

    runtime_pref: Optional[str] = None
    if len(runtimes) >= 3:
        avg = sum(runtimes) / len(runtimes)
        runtime_pref = "short" if avg < 92 else ("long" if avg > 128 else "medium")

    niche_leaning = bool(popularities) and (sum(popularities) / len(popularities)) < 18

    # ── Supplement with explicit learned weight maps ─────────────────────────
    # Learned weights are faster and more reliable than the history scan for
    # users with large interaction counts.  History scan catches early signals;
    # learned weights carry the accumulated preference over time.
    tw = user.get("tone_weights") or {}
    for t, v in sorted(tw.items(), key=lambda x: x[1], reverse=True)[:2]:
        if v > 0.5 and t not in top_tones:
            top_tones.append(t)
    top_tones = top_tones[:2]

    thw = user.get("theme_weights") or {}
    for t, v in sorted(thw.items(), key=lambda x: x[1], reverse=True)[:5]:
        if v > 0.3 and t not in top_themes:
            top_themes.append(t)
    top_themes = top_themes[:5]

    # Pacing preference — prefer learned weight map over runtime heuristic
    pw = user.get("pacing_weights") or {}
    pacing_pref: Optional[str] = None
    if pw:
        best = max(pw.items(), key=lambda x: x[1], default=(None, 0))
        if best[0] and best[1] > 0.5:
            pacing_pref = best[0]
    if not pacing_pref and runtime_pref:
        pacing_pref = ("fast" if runtime_pref == "short" else
                       "slow" if runtime_pref == "long" else "medium")

    return {
        "top_tones":    top_tones,
        "top_themes":   top_themes,
        "top_genres":   top_genres,
        "runtime_pref": runtime_pref,
        "pacing_pref":  pacing_pref,
        "niche_leaning": niche_leaning,
        "history_size": len(history_ids),
    }


def _reason_for(
    movie: dict,
    user: dict,
    *,
    in_collab: bool,
    is_reintro: bool,
    taste: "dict | None" = None,
) -> str:
    """Generate a personalised, contextual recommendation reason.

    Priority ladder:
      1. Re-intro / collab (structural signals)
      2. Theme overlap with saved/watched history (most specific)
      3. Tone + genre combo from history
      4. Pacing observation (when enough history)
      5. Runtime preference match
      6. Documentary-specific reasons
      7. Learned genre weight (requires ≥ 3 to avoid one-save triggers)
      8. Onboarding genre overlap
      9. Quality / niche fallback
    """
    if is_reintro:
        return "Worth a second look"
    if in_collab:
        return "Loved by people with your taste"

    card         = movie.get("card") or {}
    franchise    = card.get("franchise")
    franchise_name = (
        franchise.get("name") if isinstance(franchise, dict)
        else franchise if isinstance(franchise, str) else None
    )
    mg           = set(movie.get("genres") or [])
    movie_tone   = card.get("tone", "neutral")
    movie_themes = set(card.get("themes") or [])
    movie_pacing = card.get("pacing", "medium")
    movie_rt     = movie.get("runtime") or 0
    gw           = user.get("genre_weights") or {}

    profile      = taste or {}
    top_tones    = profile.get("top_tones") or []
    top_themes   = profile.get("top_themes") or []
    top_genres   = profile.get("top_genres") or []
    runtime_pref = profile.get("runtime_pref")
    history_size = profile.get("history_size", 0)

    if history_size >= 3:
        # ── Theme match — most specific possible reason ──────────────────────
        shared = movie_themes & set(top_themes)
        if shared:
            # Pick the theme that ranks highest in the user's history
            best = min(shared, key=lambda t: top_themes.index(t) if t in top_themes else 99)
            label = _THEME_LABELS.get(best, best.replace("-", " "))
            if movie_tone == "dark":
                return f"Darker {label} — fits your saved titles"
            return f"Matches your interest in {label} stories"

        # ── Tone + genre combo ───────────────────────────────────────────────
        if movie_tone in top_tones and movie_tone != "neutral":
            matching = next((g for g in top_genres if g in mg), None)
            if matching:
                if movie_tone == "dark":
                    return f"Dark {matching} — similar tone to what you've been saving"
                return f"Light-hearted {matching} — fits your recent taste"

        # ── Pacing observation (need 5+ history for reliable pattern) ────────
        if history_size >= 5 and movie_pacing == "fast" and top_genres:
            matching = next((g for g in top_genres if g in mg), None)
            if matching:
                return f"Fast-paced {matching} — based on your viewing habits"

        # ── Runtime preference ───────────────────────────────────────────────
        if runtime_pref == "short" and movie_rt and movie_rt < 95:
            return "A shorter watch — fits your usual viewing length"
        if runtime_pref == "long" and movie_rt and movie_rt > 130:
            return "A longer film — matches your typical viewing style"

        # ── Documentary-specific ─────────────────────────────────────────────
        if "Documentary" in mg:
            if "true-crime" in movie_themes:
                return "True crime documentary — based on your saves"
            if "biographical" in movie_themes or "biographical" in top_themes:
                return "Biographical documentary worth your time"
            if top_genres and "Documentary" in top_genres:
                return "Documentary that fits your taste profile"

    # ── Learned genre signal — threshold ≥ 3 (needs multiple interactions) ──
    learned_in_film = sorted(
        ((g, gw.get(g, 0)) for g in mg if gw.get(g, 0) >= 3),
        key=lambda x: x[1], reverse=True,
    )
    if learned_in_film:
        genre = learned_in_film[0][0]
        if movie_tone == "dark":
            return f"Dark {genre} — fits your recent pattern"
        if movie_pacing == "fast":
            return f"Fast-paced {genre} based on your history"
        return f"More {genre} you're likely to enjoy"

    # ── Onboarding genre overlap ─────────────────────────────────────────────
    onboard = set(user.get("genres") or [])
    overlap  = sorted(mg & onboard)
    if overlap:
        g = overlap[0]
        if movie_tone == "dark":
            return f"Dark {g} — matches your preference"
        return f"Chosen for your {g} interest"

    if franchise_name:
        suffix = "" if franchise_name.casefold().endswith(" collection") else " collection"
        return f"Part of the {franchise_name}{suffix}"

    # ── Quality / niche fallback ─────────────────────────────────────────────
    rating = movie.get("rating") or 0
    if rating >= 8.5:
        return f"Critically acclaimed · {rating}/10"
    if profile.get("niche_leaning") and (movie.get("popularity") or 0) < 15:
        return "A lesser-known pick we think you'll appreciate"

    return "Worth a look tonight"


def _primary_reason_code(movie: dict, user: dict, *, in_collab: bool,
                         is_reintro: bool, taste: "dict | None" = None) -> str:
    """Machine-readable counterpart to `_reason_for` — a short, stable code for
    WHY a card was surfaced.  Mirrors the same priority ladder so the human
    string and the code never disagree.  Purely additive metadata for the UI /
    diagnostics; it does not touch ranking or the pool.

    Codes: reintro · collab · theme_match · tone_genre · pacing · runtime ·
           documentary · learned_genre · onboarding_genre · franchise ·
           acclaimed · niche · generic
    """
    if is_reintro:
        return "reintro"
    if in_collab:
        return "collab"

    card         = movie.get("card") or {}
    mg           = set(movie.get("genres") or [])
    movie_tone   = card.get("tone", "neutral")
    movie_themes = set(card.get("themes") or [])
    movie_pacing = card.get("pacing", "medium")
    movie_rt     = movie.get("runtime") or 0
    gw           = user.get("genre_weights") or {}

    profile      = taste or {}
    top_tones    = profile.get("top_tones") or []
    top_themes   = profile.get("top_themes") or []
    top_genres   = profile.get("top_genres") or []
    runtime_pref = profile.get("runtime_pref")
    history_size = profile.get("history_size", 0)

    if history_size >= 3:
        if movie_themes & set(top_themes):
            return "theme_match"
        if movie_tone in top_tones and movie_tone != "neutral" \
                and any(g in mg for g in top_genres):
            return "tone_genre"
        if history_size >= 5 and movie_pacing == "fast" \
                and any(g in mg for g in top_genres):
            return "pacing"
        if (runtime_pref == "short" and movie_rt and movie_rt < 95) or \
           (runtime_pref == "long" and movie_rt and movie_rt > 130):
            return "runtime"
        if "Documentary" in mg and (
            "true-crime" in movie_themes
            or "biographical" in movie_themes or "biographical" in top_themes
            or "Documentary" in top_genres
        ):
            return "documentary"

    if any(gw.get(g, 0) >= 3 for g in mg):
        return "learned_genre"
    if mg & set(user.get("genres") or []):
        return "onboarding_genre"
    code_franchise = card.get("franchise")
    if (
        isinstance(code_franchise, str) and code_franchise.strip()
        or isinstance(code_franchise, dict) and code_franchise.get("name")
    ):
        return "franchise"

    rating = movie.get("rating") or 0
    if rating >= 8.5:
        return "acclaimed"
    if profile.get("niche_leaning") and (movie.get("popularity") or 0) < 15:
        return "niche"
    return "generic"


# ---------------------------------------------------------------------------
# Band-based rotation sampling
# ---------------------------------------------------------------------------

def _band_sample(pool: list, n: int, scores: "dict[str, float] | None" = None) -> list:
    """Quality-band rotation: split pool into rating bands, shuffle within
    each band, sample proportionally.

    This is the core of rotation.  Pure top-N always returns the same titles
    because the highest-scored docs never change session to session.  Pure
    random ignores quality.  Band sampling gives:
      - Rotation  — different docs each session (shuffle within band)
      - Quality   — mostly high-rated docs (proportional band allocation)
      - Fairness  — mid-tier docs surface regularly, not never

    Band thresholds (by rating):
      excellent  ≥ 8.0   target 55% of slots
      good       ≥ 7.0   target 35% of slots
      decent     < 7.0   target 10% of slots

    If a band is undersized its shortfall is redistributed to other bands.
    """
    if not pool:
        return []
    if n >= len(pool):
        result = list(pool)
        random.shuffle(result)
        return result

    excellent = [m for m in pool if (m.get("rating") or 0) >= 8.0]
    good      = [m for m in pool if 7.0 <= (m.get("rating") or 0) < 8.0]
    decent    = [m for m in pool if (m.get("rating") or 0) < 7.0]

    # Shuffle within each band for rotation
    random.shuffle(excellent)
    random.shuffle(good)
    random.shuffle(decent)

    exc_want    = min(len(excellent), round(n * 0.55))
    good_want   = min(len(good),      round(n * 0.35))
    decent_want = min(len(decent),    max(0, n - exc_want - good_want))

    taken = (
        excellent[:exc_want] +
        good[:good_want] +
        decent[:decent_want]
    )

    # Redistribute shortfall from any band exhausted below its target
    shortfall = n - len(taken)
    if shortfall > 0:
        leftovers = (
            excellent[exc_want:] +
            good[good_want:] +
            decent[decent_want:]
        )
        random.shuffle(leftovers)
        taken += leftovers[:shortfall]

    random.shuffle(taken)   # mix bands so excellent/good/decent are interleaved
    return taken[:n]


# ---------------------------------------------------------------------------
# Controlled variety helpers
# ---------------------------------------------------------------------------

def _adjacent_genres_for(selected: set) -> set:
    """Return the union of adjacent genres for all selected genres,
    minus the selected genres themselves.

    e.g. selected={"Documentary"} → {"History","Biography","Crime","News","Sport"}
    """
    adjacent: set = set()
    for g in selected:
        adjacent |= set(ADJACENT_GENRES.get(g, []))
    return adjacent - selected


def _tone_guard_for_genres(selected_genres: set) -> frozenset:
    """Return the tone values that adjacent/wildcard candidates MUST NOT have.

    Returns frozenset({"light"}) for dark-identity genres (Horror, War, ...),
    frozenset({"dark"}) for light-identity genres (Comedy, Family, ...), or
    frozenset() when genres conflict or carry no strong tonal identity.

    Conflict rule: if selected genres span both ends of the tonal spectrum
    (e.g. Horror + Comedy) the guard is disabled to avoid over-restricting
    the variety pool — better to show a mild mismatch than an empty feed.
    """
    blocks_light = any("light" in GENRE_TONE_GUARDS.get(g, frozenset()) for g in selected_genres)
    blocks_dark  = any("dark"  in GENRE_TONE_GUARDS.get(g, frozenset()) for g in selected_genres)
    if blocks_light and blocks_dark:
        return frozenset()   # conflict — disable guard
    if blocks_light:
        return frozenset({"light"})
    if blocks_dark:
        return frozenset({"dark"})
    return frozenset()


def _exploration_ratios(user: dict) -> tuple[float, float, float]:
    """Map maturity + exploration appetite → (core, adjacent, wildcard) ratios.

    Two forces shape the split:

      • Maturity — as the engine learns a user (≈25 interactions → maturity 1.0)
        the share locked to their *core selected genre* falls, so they are never
        "trapped in one genre", and same-feeling **adjacent** broadening grows.
      • Exploration appetite — exploration_weight (0.1–0.9, drifts from 0.5 based
        on reactions to non-core cards) nudges the true **wildcard** discovery
        slice up or down.

    Variety floor & discovery band (product spec):
      • Confident users (50+ interactions) never exceed ~50% core genre and
        always keep a healthy 15–25% discovery (wildcard) slice — the remainder
        is same-feeling adjacent / high-confidence broadening.
      • Brand-new (exploratory) users still lead with their chosen genre but get
        a wider wildcard slice so taste signals surface quickly.

    Always clamped so the feed is never 100% core or 100% variety, and the three
    ratios sum to ~1.0.
    """
    w = float(user.get("exploration_weight") or 0.5)
    w = max(0.1, min(0.9, w))
    m = _maturity(user)
    tier = _confidence_tier(user)
    n_inter = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )

    # Core genre dominance falls with maturity: ~0.80 cold → ~0.48 mature.
    core = 0.80 - 0.32 * m
    # True discovery grows with maturity and appetite: ~0.08 → ~0.20.
    wildcard = 0.08 + 0.10 * m + (w - 0.5) * 0.12

    if n_inter < 50:
        # ── Cold-start intent dominance (first ~50 swipes) ───────────────────
        # Hold the user's SELECTED-genre (core) share clearly dominant and keep
        # the truly-random wildcard slice modest — but never zero, so some
        # discovery always remains — so a brand-new user's chosen genres lead
        # their feed.  Both lifts decay to 0 by ~50 interactions, handing off to
        # the maturity curve below with NO genre lock-in afterwards.
        cs = (50 - n_inter) / 50.0                    # 1.0 → 0.0 across first 50
        core     = min(0.76, max(core, 0.58 + 0.16 * cs))   # ~0.76 cold → ~0.58 @ n≈50
        wildcard = max(0.10, min(wildcard, 0.16 - 0.04 * cs))
    elif tier in ("confident", "strongly_personalised"):
        # Variety floor + discovery band for well-understood users.
        wildcard = min(0.25, max(0.15, wildcard))
        core = min(core, 0.50)

    core     = max(0.40, min(0.85, core))
    wildcard = max(0.02, min(0.30, wildcard))
    adjacent = max(0.08, 1.0 - core - wildcard)

    # Normalise so the three ratios always sum to ~1.0
    total = core + adjacent + wildcard
    if total > 0 and abs(total - 1.0) > 0.001:
        core = round(core / total, 3)
        adjacent = round(adjacent / total, 3)
        wildcard = round(max(0.0, 1.0 - core - adjacent), 3)
    else:
        core, adjacent, wildcard = round(core, 3), round(adjacent, 3), round(wildcard, 3)
    return core, adjacent, wildcard


def _interleave_variety(core: list, variety: list, head: int = 0) -> list:
    """Evenly distribute variety cards throughout the core sequence.

    Computes how many core cards appear between each variety card and
    inserts variety at those regular intervals.  This gives a predictable
    rhythm — e.g. at 75% core with 25% variety: C C C V C C C V ...
    — rather than a wall of core cards followed by a cluster of variety.

    `head` emits up to that many CORE cards up-front before any variety is
    interleaved — the "trust head" that keeps the first cards anchored to the
    user's explicit intent before exploration begins.

    Any leftover variety once core is exhausted is appended at the end so the
    feed is never artificially short (the caller slices to `limit`).
    """
    if not core:
        return list(variety)
    if not variety:
        return list(core)

    head = max(0, min(head, len(core)))
    result: list = list(core[:head])
    rest_core = core[head:]
    if not rest_core:
        result.extend(variety)
        return result

    step = max(1, round(len(rest_core) / len(variety)))
    v_idx = 0
    for i, m in enumerate(rest_core):
        result.append(m)
        if (i + 1) % step == 0 and v_idx < len(variety):
            result.append(variety[v_idx])
            v_idx += 1
    if v_idx < len(variety):
        result.extend(variety[v_idx:])
    return result


# ---------------------------------------------------------------------------
# Diversity balancing
# ---------------------------------------------------------------------------

def _diversify(items: list, limit: int, max_per_genre_frac: float = 0.30) -> list:
    """Reorder `items` so no single genre dominates more than
    `max_per_genre_frac` of the output.  Items not fitting are appended
    at the end so the total length is preserved (up to `limit`)."""
    max_per = max(2, int(limit * max_per_genre_frac))
    genre_counts: dict[str, int] = {}
    result: list = []
    overflow: list = []
    for item in items:
        mg = list(item.get("genres") or [])
        at_cap = bool(mg) and all(genre_counts.get(g, 0) >= max_per for g in mg)
        if not at_cap:
            result.append(item)
            for g in mg:
                genre_counts[g] = genre_counts.get(g, 0) + 1
            if len(result) >= limit:
                break
        else:
            overflow.append(item)
    if len(result) < limit:
        result.extend(overflow[: limit - len(result)])
    return result[:limit]


def _coldstart_even_core(core_pool: list, core_target: int,
                         onboard_genres, scores: dict) -> list:
    """Cold-start even-spread of core slots across the user's SELECTED genres.

    A popular pick (e.g. Action, ~500 high-popularity titles) otherwise so
    out-scores a niche pick (e.g. Horror) that the niche genre never surfaces in
    a new user's first feeds — the same "feed ignores my picks" failure as a
    single genre drowning the rest.  `_diversify`'s cap only limits the MAX per
    genre; it guarantees no MINIMUM, and any title carrying a second genre slips
    past the cap, so one popular pick still floods the core.

    Bucket each (already score-sorted) core title under its most-salient selected
    genre, then round-robin across the buckets so every chosen genre gets a fair
    share of the core section, supply permitting.  Titles stay score-ordered
    within a bucket, so quality is preserved.  Cold-start only — matured feeds
    never call this, so there is no genre lock-in.
    """
    sel = list(onboard_genres)
    if len(sel) <= 1 or not core_pool:
        return core_pool[:core_target]
    selset = set(sel)
    buckets: dict[str, list] = {g: [] for g in sel}
    for m in core_pool:                       # core_pool is already score-sorted desc
        gl = m.get("genres") or []
        rep = next((g for g in gl if g in selset), sel[0])  # earliest selected = most salient
        buckets[rep].append(m)
    # Order genres by ascending supply so a thin pick is served before its slots
    # are eaten by an abundant one.
    draw_order = sorted(sel, key=lambda g: len(buckets[g]))
    out: list = []
    seen: set = set()
    idx = {g: 0 for g in sel}
    while len(out) < core_target:
        progressed = False
        for g in draw_order:
            b = buckets[g]
            if idx[g] < len(b):
                m = b[idx[g]]
                idx[g] += 1
                if m["id"] not in seen:
                    out.append(m)
                    seen.add(m["id"])
                    progressed = True
                    if len(out) >= core_target:
                        break
        if not progressed:
            break
    return out


# ---------------------------------------------------------------------------
# Anti-repetition + feed diversity diagnostics
# ---------------------------------------------------------------------------

def _break_feeling_streaks(items: list, max_run: int = 3) -> list:
    """Reorder `items` so the same *feeling* (effective tone group) is spaced as
    evenly as the supply allows — the anti-repetition pass.

    The naive "pull a different card forward only when the run exceeds max_run"
    greedy front-loads the dominant feeling and dumps every leftover same-feeling
    card into one long run at the tail.  Instead we *evenly distribute* feelings:

      1.  Bucket cards by feeling, preserving each bucket's internal (score)
          order.
      2.  Slice the dominant feeling into chunks no larger than the smallest run
          achievable given how many "separator" cards exist
          (``ceil(dom / (separators + 1))``, but never above ``max_run``).
      3.  Lay the chunks down, spreading the minority cards evenly into the gaps
          between them.  Minority cards are themselves de-streaked first so a
          run of one minority feeling can't replace the run we just broke.

    When the feed is genuinely one feeling (a horror purist whose whole pool is
    dark) no spacing is possible and the cards come back in their original order
    — the streak is inherent to the supply, not a packing failure.
    """
    if len(items) <= max_run:
        return list(items)

    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(_candidate_tone_group(it), []).append(it)
    if len(groups) == 1:
        return list(items)

    dom_key = max(groups, key=lambda k: len(groups[k]))
    dom = groups[dom_key]
    minority = [it for k, g in groups.items() if k != dom_key for it in g]

    # Spread the minority feelings among *themselves* first so we don't trade a
    # dominant-feeling run for a minority-feeling run.
    if len(groups) > 2:
        minority = _break_feeling_streaks(minority, max_run)

    separators = len(minority)
    # Smallest dominant run we can achieve with this many separators, capped at
    # the requested max_run (no point chunking finer than asked).
    run = max(1, math.ceil(len(dom) / (separators + 1)))
    run = min(run, max_run) if separators >= math.ceil(len(dom) / max_run) - 1 else run

    chunks = [dom[i:i + run] for i in range(0, len(dom), run)]

    # Distribute the minority cards as evenly as possible across the gaps that
    # follow each chunk.
    gaps = len(chunks)
    per_gap = [separators // gaps] * gaps
    for i in range(separators % gaps):
        per_gap[i] += 1

    result: list = []
    mi = 0
    for ci, chunk in enumerate(chunks):
        result.extend(chunk)
        take = per_gap[ci]
        result.extend(minority[mi:mi + take])
        mi += take
    if mi < separators:
        result.extend(minority[mi:])
    return result


def _cluster_key(m: dict):
    """Genre-cluster proxy — a title's most-salient (first) genre. Two titles
    sharing it are 'the same kind of thing' for run-spacing purposes."""
    g = m.get("genres") or []
    return g[0] if g else None


def _franchise(m: dict):
    return (m.get("card") or {}).get("franchise")


def _space_clusters(items: list, max_run: int = 2) -> list:
    """Cap consecutive genre-cluster / franchise runs at `max_run` (Task #23
    Step 5) WITHOUT disturbing the feeling (tone) sequence.

    Runs AFTER `_break_feeling_streaks`, whose even-distribution of feelings is
    the hard, persona-sim-critical guarantee.  To avoid regressing it, this pass
    only ever swaps two cards that share the SAME feeling: the sequence of
    feelings is provably invariant under such swaps, so the anti-repetition
    assertion stays exactly as the feeling pass left it, while cluster / franchise
    spacing improves wherever a same-feeling separator exists.

    Pure permutation (no filtering) — pool and feed length untouched.  When a run
    can only be broken by a differently-felt card (which would regress feeling)
    it is left in place: feeling spacing wins, cluster/franchise is best-effort.
    """
    n = len(items)
    if n <= max_run:
        return list(items)

    seq   = list(items)
    feels = [_candidate_tone_group(m) for m in seq]

    def _trailing(i: int, key_fn, val) -> int:
        if val is None:
            return 0
        c = 0
        j = i - 1
        while j >= 0 and key_fn(seq[j]) == val:
            c += 1
            j -= 1
        return c

    def _trailing_franchise(i: int, candidate: dict) -> int:
        franchise = _franchise(candidate)
        if not franchise:
            return 0
        c = 0
        j = i - 1
        while j >= 0 and franchise_matches(_franchise(seq[j]), franchise):
            c += 1
            j -= 1
        return c

    for i in range(max_run, n):
        if _trailing(i, _cluster_key, _cluster_key(seq[i])) < max_run and \
           _trailing_franchise(i, seq[i]) < max_run:
            continue
        # seq[i] extends a cluster/franchise run past the cap — find a later card
        # of the SAME feeling that breaks both runs and swap it in.
        for j in range(i + 1, n):
            if feels[j] != feels[i]:
                continue
            if _trailing(i, _cluster_key, _cluster_key(seq[j])) < max_run and \
               _trailing_franchise(i, seq[j]) < max_run:
                seq[i], seq[j] = seq[j], seq[i]   # feels[i]==feels[j] ⇒ feeling seq intact
                break
    return seq


def _feed_diversity_debug(items: list, head: int = 0) -> dict:
    """Genre / theme / tone spread + a repetition score for a built feed.

    repetition_score ∈ [0,1] — fraction of adjacent card pairs that share the
    same feeling (effective tone group).  0.0 = every neighbour differs in feel;
    1.0 = the whole feed is one feeling.  Lower is more varied.
    """
    n = len(items)
    genre_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    tone_counts: dict[str, int] = {}
    tone_seq: list[str] = []
    for m in items:
        for g in (m.get("genres") or []):
            genre_counts[g] = genre_counts.get(g, 0) + 1
        for t in ((m.get("card") or {}).get("themes") or []):
            theme_counts[t] = theme_counts.get(t, 0) + 1
        tg = _candidate_tone_group(m)
        tone_counts[tg] = tone_counts.get(tg, 0) + 1
        tone_seq.append(tg)

    dom_genre, dom_count = max(genre_counts.items(), key=lambda kv: kv[1], default=(None, 0))
    dominant_genre_frac = round(dom_count / n, 3) if n else 0.0

    dom_tone, dom_tone_count = max(tone_counts.items(), key=lambda kv: kv[1], default=(None, 0))
    dominant_tone_frac = round(dom_tone_count / n, 3) if n else 0.0

    same_feel_pairs = 0
    max_streak = 1 if n else 0
    cur_streak = 1 if n else 0
    for i in range(1, n):
        if tone_seq[i] == tone_seq[i - 1]:
            same_feel_pairs += 1
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 1
    repetition_score = round(same_feel_pairs / (n - 1), 3) if n > 1 else 0.0

    # Supply-aware anti-repetition diagnostics, measured on the de-streakable
    # region (everything after the protected trust head).  The trust head opens
    # the feed on the user's explicit intent and is deliberately allowed to be a
    # single-feeling run; the anti-repetition pass only operates past it.  We
    # therefore report (a) the longest streak after the head and (b) the smallest
    # streak that is *achievable* there given the non-dominant tone supply
    # (ceil(dominant / (separators + 1))).  achieved ≈ achievable ⇒ the breaker
    # is doing its job; achieved ≫ achievable ⇒ a real packing failure.
    tail_seq = tone_seq[head:] if head else tone_seq
    tn = len(tail_seq)
    tail_max_streak = 1 if tn else 0
    cur = 1 if tn else 0
    for i in range(1, tn):
        if tail_seq[i] == tail_seq[i - 1]:
            cur += 1
            tail_max_streak = max(tail_max_streak, cur)
        else:
            cur = 1
    if tn:
        tail_counts: dict[str, int] = {}
        for tg in tail_seq:
            tail_counts[tg] = tail_counts.get(tg, 0) + 1
        tail_dom = max(tail_counts.values())
        tail_sep = tn - tail_dom
        min_achievable_streak_after_head = math.ceil(tail_dom / (tail_sep + 1))
    else:
        min_achievable_streak_after_head = 0

    def _top(d: dict, k: int = 8) -> dict:
        return dict(sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:k])

    return {
        "genre_spread":            _top(genre_counts),
        "distinct_genres":         len(genre_counts),
        "dominant_genre":          dom_genre,
        "dominant_genre_frac":     dominant_genre_frac,
        "dominant_tone":           dom_tone,
        "dominant_tone_frac":      dominant_tone_frac,
        "theme_spread":            _top(theme_counts),
        "distinct_themes":         len(theme_counts),
        "tone_spread":             tone_counts,
        "distinct_tones":          len(tone_counts),
        "repetition_score":        repetition_score,
        "max_same_feeling_streak": max_streak,
        "trust_head":              head,
        "max_same_feeling_streak_after_head": tail_max_streak,
        "min_achievable_streak_after_head":   min_achievable_streak_after_head,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_feed(
    user: dict,
    limit: int = 20,
    *,
    include_other_services: bool = False,
    include_rent_buy: bool = False,
) -> list[dict]:
    """Compute a personalised feed for `user`.

    Supports large `limit` values (up to 300) for buffered queues.  The
    frontend typically requests limit=100 on first load and limit=60 on
    background refills, keeping a comfortable swipe buffer.

    Strict invariants (default mode):
      * No item from saved/watched/skipped/onboarding_rated (unless eligible
        cooldown re-intro)
      * No item shown in last 7 days (`recently_shown` LRU, 168h cooldown)
      * ALL user filters honoured: subscriptions are a HARD requirement —
        only titles available on the user's streaming services appear.
      * Band-based sampling ensures rotation — different titles each session

    Opt-in relaxations (user must explicitly enable via toggle):
      include_other_services — bypass subscription filter; show all streaming
      include_rent_buy       — also include titles available to rent or buy
    Both flags are surfaced in feed_meta.provider_bypass_triggered.
    """
    catalog = get_catalog()
    if not catalog:
        return []

    # First-run backfill (Task #23 Step 3): users who onboarded/swiped before the
    # persistent taste profile shipped have no `taste_profile` snapshot.  Derive
    # it from their accumulated weight history so they benefit immediately,
    # without needing a fresh swipe to trigger the per-action writers.  Soft:
    # scoring already reads the raw weight fields; this only denormalises them.
    if not user.get("taste_profile"):
        try:
            from taste import build_taste_profile
            _tp = build_taste_profile(user)
            user["taste_profile"] = _tp
            _bf_uid = user.get("user_id")
            if _bf_uid:
                _schedule_taste_backfill(_bf_uid, _tp)
        except Exception:
            pass

    permanently_seen = set(
        (user.get("saved") or []) +
        (user.get("watched") or []) +
        (user.get("onboarding_rated") or [])
    )
    skipped = set(user.get("skipped") or [])
    cooldown_set = _recently_shown_active(user)

    # Top genres by current learned weight — used for both reintros and reasons
    gw = user.get("genre_weights") or {}
    learned_top_genres = {
        g for g, v in sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:3] if v >= 2
    }
    reintro_eligible = await _eligible_skip_reintros(user, learned_top_genres)

    # Provider filtering stats — always counted against strict subscription rules
    # regardless of mode flags, so feed_meta always shows what strict mode sees.
    _user_subs = set(user.get("subscriptions") or [])
    _user_region = (user.get("country") or os.environ.get("TMDB_REGION", "GB")).upper()
    provider_match_count       = 0  # on at least one user subscription
    provider_rejected_count    = 0  # on a different service (wrong provider)
    rent_buy_rejected_count    = 0  # rent/buy only (no streaming option on subs)
    unavailable_rejected_count = 0  # no provider data at all (unenriched)

    # Reality-TV suppression + niche-filler / fallback diagnostics
    _reality_ok            = _reality_allowed(user)
    reality_suppressed_count = 0
    low_vote_suppressed_count = 0
    fallback_ids: set      = set()   # ids admitted via any broadening path
    rejection_debug: list[dict] = []  # capped sample of every rejection reason

    def _record_pool_reject(m: dict, reason: str) -> None:
        if len(rejection_debug) < 80:
            rejection_debug.append({
                "title":            m.get("title"),
                "id":               m.get("id"),
                "stage":            "pool",
                "rejection_reason": reason,
                "genres":           m.get("genres"),
                "vote_count":       m.get("vote_count"),
            })

    # Build candidate pool
    pool = []
    for m in catalog:
        mid = m["id"]
        if mid in permanently_seen:
            continue
        if mid in cooldown_set:
            continue
        if mid in skipped and mid not in reintro_eligible:
            continue
        # Reality TV is suppressed unless explicitly selected / repeatedly liked
        if not _reality_ok and _is_reality(m):
            reality_suppressed_count += 1
            _record_pool_reject(m, "reality_suppressed")
            continue

        # Tally strict-mode provider stats for feed_meta diagnostics
        if _user_subs and catalog_quality_gate(m, user_region=_user_region, user=user):
            _avail = set(m.get("available_on") or [])
            _rent  = set(m.get("rent_on")  or [])
            _buy   = set(m.get("buy_on")   or [])
            if _avail & _user_subs:
                provider_match_count += 1
            elif not _avail and not _rent and not _buy:
                unavailable_rejected_count += 1
            elif not _avail and (_rent | _buy):
                rent_buy_rejected_count += 1
            else:
                provider_rejected_count += 1

        # Apply the mode-appropriate subscription filter
        if include_other_services:
            # User explicitly opted in: show titles from all streaming services
            if not movie_matches_no_subs(m, user):
                continue
        elif include_rent_buy:
            # User explicitly opted in: include rent/buy alongside subscriptions
            if not movie_matches_no_subs(m, user):
                continue
            if _user_subs:
                _avail = set(m.get("available_on") or [])
                _rent  = set(m.get("rent_on")  or [])
                _buy   = set(m.get("buy_on")   or [])
                if not (_avail & _user_subs) and not (_rent | _buy):
                    continue  # not on subs and not rentable/buyable
        else:
            # DEFAULT: strict mode — subscription is a HARD requirement
            if not movie_matches(m, user):
                continue

        pool.append(m)

    # Snapshot pool size BEFORE any emergency / broadening re-admission so
    # debug output can show pool_before_filters (whole catalog) vs
    # pool_after_filters (survived strict filters) vs the final broadened pool.
    pool_before_filters = len(catalog)
    pool_after_filters  = len(pool)

    # EMERGENCY REINTRODUCTION: if the filtered pool is critically small,
    # reintroduce skipped items (they may have been rejected before tastes
    # converged). This prevents empty-feed states for narrow-filter users.
    POOL_EMERGENCY = 30
    if len(pool) < POOL_EMERGENCY and skipped:
        for m in catalog:
            mid = m["id"]
            if mid in permanently_seen or mid in cooldown_set:
                continue
            if mid not in skipped:
                continue
            if not _reality_ok and _is_reality(m):
                continue
            if not movie_matches(m, user):
                continue
            reintro_eligible.add(mid)
            fallback_ids.add(mid)
            pool.append(m)

    # ULTRA-EMERGENCY: pool STILL near-empty (user swiped everything in their
    # filtered universe within the cooldown window). Bypass the recently-shown
    # LRU so they at least see something — these items still get a soft
    # re-intro reason.
    POOL_ULTRA_EMERGENCY = 8
    if len(pool) < POOL_ULTRA_EMERGENCY:
        existing = {m["id"] for m in pool}
        for m in catalog:
            mid = m["id"]
            if mid in existing or mid in permanently_seen:
                continue
            if not _reality_ok and _is_reality(m):
                continue
            if not movie_matches(m, user):
                continue
            reintro_eligible.add(mid)
            fallback_ids.add(mid)
            pool.append(m)
        if pool:
            logger.info(f"Pool ultra-emergency: bypassed cooldown LRU, pool now {len(pool)}")

    # Adaptive popularity cap — keep more for cold-start, narrower for mature users.
    # IMPORTANT: always preserve ALL genre-matching titles for cold/mid users so
    # the genre preference signal actually gets a chance to rank them.
    maturity = _maturity(user)
    # onboard_genres hoisted here — used by both cap logic and intent enforcement below
    onboard_genres = set(user.get("genres") or [])
    cap = max(500, int(TARGET_POOL * (1.0 - 0.6 * maturity)))
    if len(pool) > cap:
        if onboard_genres and maturity < 0.6:
            # Phase 1: keep every title that matches any selected genre (no cap)
            genre_ids = {m["id"] for m in pool if set(m.get("genres") or []) & onboard_genres}
            genre_pool = [m for m in pool if m["id"] in genre_ids]
            non_genre  = [m for m in pool if m["id"] not in genre_ids]
            # Phase 2: fill remainder slots with most-popular non-matching titles
            non_genre.sort(key=lambda m: m.get("popularity", 0), reverse=True)
            remainder = max(0, cap - len(genre_pool))
            pool = genre_pool + non_genre[:remainder]
        else:
            pool.sort(key=lambda m: m.get("popularity", 0), reverse=True)
            pool = pool[:cap]

    # ── ADAPTIVE COOLDOWN BYPASS for thin core-genre pools ───────────────────
    # The 7-day cooldown is designed for large catalogs (1000+ titles). For
    # narrow genres under a strict subscription filter (e.g. Horror on
    # Netflix = 19 titles), ALL core titles enter cooldown after a single
    # session, leaving the user with 0% of their chosen genre and 100% adjacent
    # titles.  Fix: when fewer than POOL_THIN_THRESHOLD core-genre titles
    # survive the cooldown, re-admit recently-shown core titles so the user
    # cycles through their full (small) genre catalog every session.
    if onboard_genres and cooldown_set:
        core_in_pool = sum(1 for m in pool if set(m.get("genres") or []) & onboard_genres)
        if core_in_pool < POOL_THIN_THRESHOLD:
            existing_ids = {m["id"] for m in pool}
            readded = 0
            for m in catalog:
                mid = m["id"]
                if mid in existing_ids or mid in permanently_seen:
                    continue
                if mid not in cooldown_set:
                    continue  # only re-admit items that WERE excluded by cooldown
                if mid in skipped and mid not in reintro_eligible:
                    continue
                if not movie_matches(m, user):
                    continue
                if set(m.get("genres") or []) & onboard_genres:
                    pool.append(m)
                    existing_ids.add(mid)
                    fallback_ids.add(mid)
                    readded += 1
            if readded:
                logger.info(
                    f"[adaptive-cooldown] Re-admitted {readded} core-genre titles for "
                    f"{user['user_id']} (core_in_pool={core_in_pool}, "
                    f"genres={sorted(onboard_genres)}, subs={user.get('subscriptions')})"
                )

    # ── POOL FLOOR ──────────────────────────────────────────────────────────
    # Keep the pool above POOL_FLOOR whenever the catalogue allows, so the feed
    # never feels "all caught up" during normal use.  Broadening is intelligent
    # and stays strictly within the user's filters: it re-admits cooldown'd
    # titles (titles already shown >0 but still matching every filter), ordered
    # by quality + popularity so high-quality, strong-vote titles come back
    # first rather than niche filler.  No subscription/provider relaxation here
    # — that remains an explicit opt-in via include_other_services.
    if len(pool) < POOL_FLOOR and cooldown_set:
        existing_ids = {m["id"] for m in pool}
        readmit = []
        for m in catalog:
            mid = m["id"]
            if mid in existing_ids or mid in permanently_seen:
                continue
            if mid not in cooldown_set:
                continue
            if mid in skipped and mid not in reintro_eligible:
                continue
            if not _reality_ok and _is_reality(m):
                continue
            if not movie_matches(m, user):
                continue
            readmit.append(m)
        # Quality-first ordering: rating then popularity then vote_count
        readmit.sort(
            key=lambda m: (
                float(m.get("rating") or 0),
                float(m.get("popularity") or 0),
                int(m.get("vote_count") or 0),
            ),
            reverse=True,
        )
        need = POOL_FLOOR - len(pool)
        for m in readmit[:need]:
            pool.append(m)
            fallback_ids.add(m["id"])
        if readmit:
            logger.info(
                f"[pool-floor] user={user['user_id']} re-admitted "
                f"{min(need, len(readmit))} cooldown'd titles "
                f"(pool {pool_after_filters} → {len(pool)})"
            )

    # Pull collaborative signal in parallel (doesn't block scoring)
    collab_set = await _collaborative_boost_set(user)

    # ── Load community caches for this feed build (Task #38) ──────────────
    # Soft signals only: pool stays identical, we just re-rank.  Local
    # per-request variables avoid cross-request contamination.
    total_interactions = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    if total_interactions < 20:
        # New-user mode: compute a cluster-aligned boost once per build
        from global_learning import compute_new_user_boost
        new_user_boost_map: "dict[str, float] | None" = await compute_new_user_boost(user, catalog, db)
    else:
        new_user_boost_map = None
    # Community quality score cache for all users (light nudge)
    from global_learning import get_community_quality_scores
    community_cache_map: "dict[str, float] | None" = await get_community_quality_scores(db)
    # Discovery success scores — nudge adjacent/wildcard items that performed
    # well when previously shown as discovery cards.
    from global_learning import get_discovery_scores
    discovery_score_map: "dict[str, float] | None" = await get_discovery_scores(db)
    # Self-cleaning weak-title penalty — soft demotion for titles that have
    # high impressions but very low engagement (never hard removal).
    from global_learning import get_self_cleaning_flags
    self_cleaning_set: "set[str] | None" = await get_self_cleaning_flags(db)

    # Boost genres found in recent search history (search-frequency signal)
    search_genre_boost: dict[str, float] = {}
    search_history = user.get("search_history") or []
    if search_history:
        all_genres: set = {g for m in catalog for g in (m.get("genres") or [])}
        for q_item in search_history[-10:]:
            q_lower = q_item.lower()
            for g in all_genres:
                if q_lower in g.lower() or g.lower() in q_lower:
                    search_genre_boost[g] = search_genre_boost.get(g, 0) + 0.08

    current_year = datetime.now(timezone.utc).year

    # ── STRICT GENRE INTENT ENFORCEMENT ──────────────────────────────────────
    # When the user has explicitly selected genres at onboarding, those genres
    # define the PRIMARY category of the feed — not just a boost signal.
    #
    # Strategy:
    #   1. Partition the filtered pool into intent_pool (matches ≥1 selected
    #      genre) and fill_pool (no match).
    #   2. Score each partition independently with the same hybrid scorer so
    #      quality/freshness/tone govern ranking *within* each group.
    #   3. Allocate ≥INTENT_RATIO of output slots to intent_pool when supply
    #      allows. The composition stage enforces this — no ranking signal can
    #      displace intent.
    #   4. Fill remaining slots from fill_pool only when intent_pool exhausted.
    #   5. Log every decision with enough detail to debug "why is a non-
    #      Documentary in a Documentary feed?"
    #
    # Session fatigue excludes explicitly selected genres so Documentary fatigue
    # never suppresses the content the user actually asked for.
    #
    # Pool split: core (selected genres) / adjacent (curated related genres) /
    # wildcard (everything else).  Ratios come from _exploration_ratios(user)
    # which reads exploration_weight and maps [0.1,0.9] → ~75/17/8% by default.

    INTENT_LOW_WATER = 40     # emit warning if core_pool shrinks below this

    # Fatigue: exclude onboard genres so they're never penalised
    genre_fatigue = _session_genre_fatigue(user, exclude_genres=onboard_genres)
    if genre_fatigue:
        logger.debug(f"Genre fatigue for {user['user_id']}: {genre_fatigue}")

    # ── 3-WAY POOL PARTITION ─────────────────────────────────────────────────
    # core     — exactly matches selected genres (Documentary stays Documentary)
    # adjacent — thematically related genres from the curated ADJACENT_GENRES map
    # wildcard — everything else (true exploration)
    subscription_expanded       = False
    subscription_expanded_count = 0
    _tone_blocked               = frozenset()   # tone values blocked for adj/wildcard
    _tone_relaxed               = frozenset()   # blocked tones relaxed by behaviour
    tone_rejected_adjacent      = 0
    tone_rejected_wildcard      = 0
    tone_rejected_doc_continuity = 0
    tone_debug: list[dict]      = []            # per-rejected-candidate detail (capped)
    genre_match_mode            = "none"        # set to any/strict_all when genres exist

    if onboard_genres:
        adjacent_genres = _adjacent_genres_for(onboard_genres)
        # Combined genres are NOT a hard lock by default: a title is "core" if it
        # matches ANY selected genre (OR).  Only when the user has explicitly
        # opted into strict filtering (and selected >1 genre) do we require the
        # title to match ALL selected genres (AND).
        _strict_genres = bool(user.get("strict_genres")) and len(onboard_genres) > 1
        genre_match_mode = "strict_all" if _strict_genres else "any"
        if _strict_genres:
            core_ids = {m["id"] for m in pool
                        if onboard_genres <= set(m.get("genres") or [])}
        else:
            core_ids = {m["id"] for m in pool
                        if set(m.get("genres") or []) & onboard_genres}
        adjacent_ids = {m["id"] for m in pool
                        if m["id"] not in core_ids
                        and set(m.get("genres") or []) & adjacent_genres}

        # ── EXPLICIT FALLBACK LADDER (Task #8) ────────────────────────────────
        # Spec ladder rungs (descending similarity):
        #   R1. exact niche  — already in core_ids (selected genre match)
        #   R2. same genre + tone     — selected genre + matching tone (in core)
        #   R3. same themes           — outside core, shares user's top themes
        #   R4. same pacing+runtime   — outside core, matches user's pacing pref
        #   R5. same audience+mood    — outside core, matches audience/tone
        #   R6. adjacent genre        — curated ADJACENT_GENRES (already R6)
        #   R7. broader exploration   — everything else (= wildcard)
        # R1/R2/R6 are already captured by the core/adjacent split.  Rungs R3,
        # R4, R5 are explicit promotions from wildcard into adjacent below.
        # They only fire when (core_pool + adjacent_pool) is still thin, so
        # well-served users see a clean 3-tier feed unchanged.
        _theme_weights   = user.get("theme_weights") or {}
        _pacing_weights  = user.get("pacing_weights") or {}
        _tone_weights    = user.get("tone_weights")   or {}
        _top_liked_themes = {
            t for t, v in sorted(_theme_weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
            if v >= 1.0
        }
        _top_pacings = {
            p for p, v in sorted(_pacing_weights.items(), key=lambda kv: kv[1], reverse=True)[:2]
            if v >= 1.0
        }
        _top_tones = {
            t for t, v in sorted(_tone_weights.items(), key=lambda kv: kv[1], reverse=True)[:3]
            if v >= 1.0
        }

        # User-preferred runtime band, derived from their saved/watched_liked
        # history.  Used in rung R4 alongside pacing so "movie length" is part
        # of the same-pacing rung.  Bands: short (≤90), standard (91-130),
        # long (131-170), epic (>170).  TV series use total_runtime.
        def _runtime_band(m: dict) -> str:
            rt = m.get("runtime") or m.get("total_runtime") or 0
            if rt and rt <= 90:    return "short"
            if rt and rt <= 130:   return "standard"
            if rt and rt <= 170:   return "long"
            if rt:                 return "epic"
            return "unknown"
        _liked_ids = set(user.get("saved_movies") or []) | set(user.get("watched_liked") or [])
        if _liked_ids:
            _band_counts: dict[str, int] = {}
            for _m in pool:
                if _m["id"] in _liked_ids:
                    b = _runtime_band(_m)
                    if b != "unknown":
                        _band_counts[b] = _band_counts.get(b, 0) + 1
            _preferred_runtime_bands = {b for b, c in _band_counts.items() if c >= 2}
        else:
            _preferred_runtime_bands = set()

        # Audience preference (rung R5) — top audience_type from liked titles.
        _preferred_audiences: set = set()
        if _liked_ids:
            _aud_counts: dict[str, int] = {}
            for _m in pool:
                if _m["id"] in _liked_ids:
                    a = (_m.get("card") or {}).get("audience_type")
                    if a:
                        _aud_counts[a] = _aud_counts.get(a, 0) + 1
            _preferred_audiences = {a for a, c in _aud_counts.items() if c >= 2}

        _ladder_promoted = {"theme": 0, "pacing_runtime": 0, "audience_mood": 0}
        _LADDER_TARGET = POOL_THIN_THRESHOLD * 2  # stop promoting once healthy

        def _ladder_size() -> int:
            return len(core_ids) + len(adjacent_ids)

        # R3 — same themes (top liked themes overlap)
        if _top_liked_themes and _ladder_size() < _LADDER_TARGET:
            for m in pool:
                if m["id"] in core_ids or m["id"] in adjacent_ids:
                    continue
                if set((m.get("card") or {}).get("themes") or []) & _top_liked_themes:
                    adjacent_ids.add(m["id"])
                    _ladder_promoted["theme"] += 1
                if _ladder_size() >= _LADDER_TARGET:
                    break

        # R4 — same pacing AND/OR runtime band
        if (_top_pacings or _preferred_runtime_bands) and _ladder_size() < _LADDER_TARGET:
            for m in pool:
                if m["id"] in core_ids or m["id"] in adjacent_ids:
                    continue
                _matches_pacing = (m.get("card") or {}).get("pacing") in _top_pacings
                _matches_runtime = (
                    _preferred_runtime_bands
                    and _runtime_band(m) in _preferred_runtime_bands
                )
                if _matches_pacing or _matches_runtime:
                    adjacent_ids.add(m["id"])
                    _ladder_promoted["pacing_runtime"] += 1
                if _ladder_size() >= _LADDER_TARGET:
                    break

        # R5 — same audience AND/OR tone (mood) signature
        if (_top_tones or _preferred_audiences) and _ladder_size() < _LADDER_TARGET:
            for m in pool:
                if m["id"] in core_ids or m["id"] in adjacent_ids:
                    continue
                _card = m.get("card") or {}
                _matches_tone     = _card.get("tone") in _top_tones
                _matches_audience = (
                    _preferred_audiences
                    and _card.get("audience_type") in _preferred_audiences
                )
                if _matches_tone or _matches_audience:
                    adjacent_ids.add(m["id"])
                    _ladder_promoted["audience_mood"] += 1
                if _ladder_size() >= _LADDER_TARGET:
                    break

        if sum(_ladder_promoted.values()):
            logger.info(
                f"[fallback-ladder] user={user['user_id']} "
                f"core={len(core_ids)} "
                f"promoted_by_theme={_ladder_promoted['theme']} "
                f"promoted_by_pacing_runtime={_ladder_promoted['pacing_runtime']} "
                f"promoted_by_audience_mood={_ladder_promoted['audience_mood']} "
                f"target={_LADDER_TARGET}"
            )

        core_pool     = [m for m in pool if m["id"] in core_ids]
        adjacent_pool = [m for m in pool if m["id"] in adjacent_ids]
        wildcard_pool = [m for m in pool
                         if m["id"] not in core_ids and m["id"] not in adjacent_ids]

        # Subscription filtering is a HARD REQUIREMENT in default mode.
        # Adjacent tiles from the SAME subscriptions fill the thin-pool
        # shortfall without injecting off-service titles.  Cross-service or
        # rent/buy expansion only fires when include_other_services or
        # include_rent_buy was set by the user as an explicit opt-in.
        subs_set = _user_subs

        # ── TONE GUARD ─────────────────────────────────────────────────────
        # Adjacent and wildcard candidates must be tonally compatible with the
        # selected genre.  Horror/War/Thriller/Crime feeds never get
        # light/holiday/feel-good titles; Comedy/Romance/Family feeds never get
        # dark/brutal ones.  "neutral" always passes.  A candidate's tone is its
        # *effective* tone group (card.tone + themes + audience), so a feel-good
        # Christmas comedy reads as "light" and a war drama reads as "dark"
        # regardless of their raw heuristic tone.
        #
        # Two relaxations keep this from feeling over-restrictive:
        #   • behaviour override — a blocked tone the user demonstrably enjoys
        #     (learned tone/theme weights) is allowed back in.
        #   • Horror+Comedy conflict — when selected genres span both ends of
        #     the spectrum, _tone_guard_for_genres already returns no block.
        # Documentary feeds additionally enforce subtype continuity so doc
        # exploration stays within coherent doc subtypes.
        _raw_blocked = _tone_guard_for_genres(onboard_genres)
        _tone_relaxed = frozenset(
            t for t in _raw_blocked if _behavior_supports_tone(user, t)
        )
        _tone_blocked = _raw_blocked - _tone_relaxed
        _doc_selected = "Documentary" in onboard_genres
        # User's preferred doc subtypes (only used for continuity when known).
        _user_doc_subtypes = {
            t for t in DOC_SUBTYPE_THEMES
            if float((user.get("theme_weights") or {}).get(t, 0)) >= 1.0
        }

        def _tone_reject(m: dict, tier: str) -> "str | None":
            """Return a rejection_reason if `m` must be filtered, else None."""
            group = _candidate_tone_group(m)
            if _tone_blocked and group in _tone_blocked:
                return f"tone_incompatible:{group}_in_{'/'.join(sorted(onboard_genres))}"
            # Documentary subtype continuity: a documentary candidate that
            # carries NO recognised subtype, while the user has clear subtype
            # preferences, is emotionally random within a doc feed.
            if (
                _doc_selected
                and _user_doc_subtypes
                and "Documentary" in set(m.get("genres") or [])
            ):
                cand_subtypes = set((m.get("card") or {}).get("themes") or []) & DOC_SUBTYPE_THEMES
                if cand_subtypes and not (cand_subtypes & _user_doc_subtypes):
                    return "doc_subtype_discontinuity"
            return None

        def _record_reject(m: dict, tier: str, reason: str) -> None:
            if len(tone_debug) < 50:
                tone_debug.append({
                    "title":            m.get("title"),
                    "id":               m.get("id"),
                    "tier":             tier,
                    "selected_genre":   sorted(onboard_genres),
                    "candidate_genre":  m.get("genres"),
                    "candidate_tone":   _candidate_tone_group(m),
                    "tone_compatible":  False,
                    "rejection_reason": reason,
                })
            logger.debug(
                f"[tone-guard] REJECT {tier} '{m.get('title')}' reason={reason} "
                f"genres={m.get('genres')} selected={sorted(onboard_genres)}"
            )

        if _tone_blocked or (_doc_selected and _user_doc_subtypes):
            _adj_filtered = []
            for m in adjacent_pool:
                reason = _tone_reject(m, "adjacent")
                if reason:
                    tone_rejected_adjacent += 1
                    if reason == "doc_subtype_discontinuity":
                        tone_rejected_doc_continuity += 1
                    _record_reject(m, "adjacent", reason)
                else:
                    _adj_filtered.append(m)
            adjacent_pool = _adj_filtered

            _wild_filtered = []
            for m in wildcard_pool:
                reason = _tone_reject(m, "wildcard")
                if reason:
                    tone_rejected_wildcard += 1
                    if reason == "doc_subtype_discontinuity":
                        tone_rejected_doc_continuity += 1
                    _record_reject(m, "wildcard", reason)
                else:
                    _wild_filtered.append(m)
            wildcard_pool = _wild_filtered

            if tone_rejected_adjacent + tone_rejected_wildcard:
                logger.info(
                    f"[tone-guard] active selected={sorted(onboard_genres)} "
                    f"blocked={sorted(_tone_blocked)} relaxed={sorted(_tone_relaxed)} "
                    f"rejected adj={tone_rejected_adjacent} wild={tone_rejected_wildcard} "
                    f"doc_continuity={tone_rejected_doc_continuity}"
                )
    else:
        adjacent_genres = set()
        core_pool     = pool
        adjacent_pool = []
        wildcard_pool = []

    # ── Pool health diagnosis ─────────────────────────────────────────────────
    # Determines the most likely reason the feed could feel thin, surfaced in
    # feed_meta so the frontend and debug tooling have actionable context.
    _subs_active = bool(_user_subs)
    if not onboard_genres:
        empty_state_reason: Optional[str] = None
    elif len(core_pool) == 0:
        empty_state_reason = "subscription_exhausted" if _subs_active else "cooldown_exhausted"
    elif len(core_pool) < CORE_CRITICAL_THRESHOLD:
        empty_state_reason = "subscription_limited" if _subs_active else "catalog_thin"
    elif len(core_pool) < POOL_THIN_THRESHOLD:
        empty_state_reason = "thin_pool"
    else:
        empty_state_reason = None

    # ── Fallback reason — describes the active adjacent fill strategy ─────────
    # "adjacent_same_subs": core pool is thin; adjacent genres on same
    #   subscriptions are being used to pad the feed (no off-service injection).
    # "subscription_exhausted": nothing at all — user has seen everything.
    if not onboard_genres or not _user_subs:
        fallback_reason: Optional[str] = None
    elif len(core_pool) == 0:
        fallback_reason = "subscription_exhausted"
    elif len(core_pool) < POOL_THIN_THRESHOLD and adjacent_pool:
        fallback_reason = "adjacent_same_subs"
    else:
        fallback_reason = None

    intent_low = bool(onboard_genres) and len(core_pool) < INTENT_LOW_WATER

    # Compute negative-signal maturity once here (avoids recompute per card).
    neg_maturity = _neg_maturity(user)

    # ── LEARNED DISLIKE GUARD ─────────────────────────────────────────────────
    # Extends the tone guard: after the user has built meaningful skip history,
    # adjacent and wildcard pools are filtered for auto-blocked languages and
    # decades.  Only fires once neg_maturity ≥ 0.4 (≈5 interactions) to
    # avoid cold-start over-restriction; hard-blocked users are the exception.
    _auto_blocked_langs   = set(user.get("auto_blocked_languages") or [])
    _auto_blocked_decades = set(user.get("auto_blocked_decades") or [])
    if onboard_genres and neg_maturity >= 0.4 and (_auto_blocked_langs or _auto_blocked_decades):
        def _dislike_ok(m: dict) -> bool:
            _lang = m.get("original_language") or "en"
            if _auto_blocked_langs and _lang in _auto_blocked_langs:
                return False
            if _auto_blocked_decades:
                _yr  = m.get("year") or 0
                _dec = f"{(_yr // 10) * 10}s" if _yr else "unknown"
                if _dec in _auto_blocked_decades:
                    return False
            return True
        _before_adj  = len(adjacent_pool)
        _before_wild = len(wildcard_pool)
        adjacent_pool = [m for m in adjacent_pool if _dislike_ok(m)]
        wildcard_pool = [m for m in wildcard_pool if _dislike_ok(m)]
        _rej_adj  = _before_adj  - len(adjacent_pool)
        _rej_wild = _before_wild - len(wildcard_pool)
        if _rej_adj + _rej_wild:
            logger.info(
                f"[dislike-guard] user={user['user_id']} "
                f"adj_rejected={_rej_adj} wild_rejected={_rej_wild} "
                f"blocked_langs={sorted(_auto_blocked_langs)} "
                f"blocked_decades={sorted(_auto_blocked_decades)}"
            )

    # ── EXPLORATION QUALITY FLOOR ─────────────────────────────────────────────
    # Adjacent and wildcard candidates must clear a quality bar (vote count OR
    # rating OR popularity) so obscure low-vote niche filler never dominates the
    # broadening/exploration tiers.  Core (the user's explicit genre) is exempt —
    # the user asked for it, so quality is not a gate there.  This guards against
    # "emotionally-random" low-signal recommendations.
    _before_adj_q = len(adjacent_pool)
    _before_wild_q = len(wildcard_pool)
    adjacent_pool = [m for m in adjacent_pool if _explore_quality_ok(m)]
    wildcard_pool = [m for m in wildcard_pool if _explore_quality_ok(m)]
    low_vote_suppressed_count += (_before_adj_q - len(adjacent_pool)) + \
                                 (_before_wild_q - len(wildcard_pool))

    # Score each partition with the same hybrid scorer.
    # Scores are cached in a local dict so we can expose them in debug signals
    # without modifying the shared catalog objects.
    scores: dict[str, float] = {}

    # ── Heavy-user detection (Task #23 Step 6) ───────────────────────────────
    # Heavy = a lot of swipe history OR a thin supply of fresh, unseen titles.
    # In heavy-user mode FRESH beats RELEVANCE: reintroduced / re-admitted
    # (previously-seen) titles are pushed below genuinely fresh ones so the user
    # keeps discovering rather than re-seeing.  Pool is untouched — this is a
    # pure score nudge.
    _interactions_hu = (
        len(user.get("saved") or []) +
        len(user.get("watched") or []) +
        len(user.get("skipped") or []) +
        len(user.get("onboarding_rated") or [])
    )
    _fresh_count = sum(
        1 for m in pool
        if m["id"] not in fallback_ids and m["id"] not in skipped
    )
    heavy_user = (_interactions_hu >= HEAVY_USER_SWIPES) or (_fresh_count < HEAVY_FRESH_FLOOR)

    _gw_taste = user.get("genre_weights") or {}

    def _is_weak_taste(m: dict) -> bool:
        """No explicit/learned positive genre signal for this title."""
        _mg = set(m.get("genres") or [])
        if _mg & onboard_genres:
            return False
        return not any(_gw_taste.get(g, 0) > 0 for g in _mg)

    def _post_score_adjust(
        m: dict,
        base: float,
        *,
        new_user_boost: "dict[str, float] | None" = None,
        discovery_scores: "dict[str, float] | None" = None,
        self_cleaning: "set[str] | None" = None,
        is_discovery_pool: bool = False,
    ) -> float:
        mid = m["id"]
        is_reseen = (mid in fallback_ids) or (mid in reintro_eligible and mid in skipped)
        # Heavy-user mode: freshness before relevance (reintro stays last resort).
        if heavy_user and is_reseen:
            base -= HEAVY_REINTRO_PENALTY
        # Absolute last-resort floor (Task #23 Step 7): a title that is
        # simultaneously weakest-quality (Tier D) AND previously skipped AND a
        # weak taste match sinks to the very bottom — but stays in the pool.
        if (
            mid in skipped
            and (m.get("card") or {}).get("quality_tier") == "D"
            and _is_weak_taste(m)
        ):
            base -= LAST_RESORT_PENALTY
        # Community new-user boost (Task #38): for users with <20 interactions,
        # add a community-derived bonus when available.  Light — this is applied
        # inside _post_score_adjust so it runs after all personal signals.
        if new_user_boost is not None and mid in new_user_boost:
            base += new_user_boost[mid]
        # Discovery success nudge (Task #38): titles that performed well when
        # shown in adjacent/wildcard slots get a small boost in discovery pools.
        # Only applied to adjacent/wildcard items so core ranking is untouched.
        if is_discovery_pool and discovery_scores is not None and mid in discovery_scores:
            base += discovery_scores[mid] * 0.5  # max ~0.5 when dss=1.0
        # Self-cleaning penalty (Task #38): weak titles with high impressions
        # but low engagement get a soft demotion — never hard removal.
        if self_cleaning is not None and mid in self_cleaning:
            base -= 0.35
        return base

    def _score_sort(
        p: list,
        *,
        community_cache: "dict[str, float] | None" = None,
        new_user_boost: "dict[str, float] | None" = None,
        discovery_scores: "dict[str, float] | None" = None,
        self_cleaning: "set[str] | None" = None,
        is_discovery_pool: bool = False,
    ) -> list:
        for m in p:
            scores[m["id"]] = _post_score_adjust(
                m,
                _hybrid_score(
                    m, user,
                    maturity=maturity,
                    neg_maturity=neg_maturity,
                    collab_set=collab_set,
                    learned_top_genres=learned_top_genres,
                    current_year=current_year,
                    extra_genre_boost=search_genre_boost or None,
                    genre_fatigue=genre_fatigue or None,
                    community_cache=community_cache,
                ),
                new_user_boost=new_user_boost,
                discovery_scores=discovery_scores,
                self_cleaning=self_cleaning,
                is_discovery_pool=is_discovery_pool,
            )
        p.sort(key=lambda m: scores[m["id"]], reverse=True)
        return p

    _score_sort(core_pool, community_cache=community_cache_map, new_user_boost=new_user_boost_map,
                self_cleaning=self_cleaning_set)
    if adjacent_pool:
        _score_sort(adjacent_pool, community_cache=community_cache_map, new_user_boost=new_user_boost_map,
                    discovery_scores=discovery_score_map, self_cleaning=self_cleaning_set, is_discovery_pool=True)
    if wildcard_pool:
        _score_sort(wildcard_pool, community_cache=community_cache_map, new_user_boost=new_user_boost_map,
                    discovery_scores=discovery_score_map, self_cleaning=self_cleaning_set, is_discovery_pool=True)

    # Debug tracking — populated below
    adjacent_ids_set: set    = set()
    wildcard_ids_set: set    = set()
    core_slots_used: int     = 0
    adjacent_slots_used: int = 0
    wildcard_slots_used: int = 0
    core_ratio = adjacent_ratio = wildcard_ratio = 0.0

    # Hard caps for legacy (pre-2000) titles per feed batch. Soft re-ranking is
    # not enough when pools are thin; we enforce absolute ceilings so the feed
    # stays ~95% modern/relevant regardless of pool state.
    #
    # Limits scale with batch size: pre-2000 ≤ 5% (max 2 in a batch of 20),
    # pre-1980 ≤ 1 card, pre-1960 ≤ 1 card (and both are classic_exception only).
    MAX_TIER_C_PER_FEED = max(1, limit // 20)     # 1 per 20 cards
    MAX_PRE_1980_PER_FEED = 1
    MAX_PRE_1960_PER_FEED = 1

    def _age_tier_filter(selected_list: list) -> list:
        """Enforce hard caps on legacy content post-selection."""
        kept, tier_c_count = [], 0
        for m in selected_list:
            y = int(m.get("year") or 0)
            if not y or y >= 2000:
                kept.append(m)
                continue
            # ALL pre-2000 titles share the Tier C cap (including pre-1980 / pre-1960)
            if tier_c_count >= MAX_TIER_C_PER_FEED:
                continue
            tier_c_count += 1
            kept.append(m)
        return kept

    if not onboard_genres:
        # No genre selection — classic band-sampled path, all slots are "core"
        sampled  = _band_sample(core_pool, limit * 3)
        selected = _diversify(sampled, limit)
        # Hard cap legacy content BEFORE anti-repetition passes so they don't
        # accidentally push modern cards out via streak-breaking swaps.
        selected = _age_tier_filter(selected)
        # Feeling spacing (the hard guarantee), then best-effort genre-cluster /
        # franchise spacing layered on top without disturbing it (Task #23 Step 5).
        selected = _break_feeling_streaks(selected, max_run=3)
        selected = _space_clusters(selected, max_run=2)
        _feed_head = 0
        core_slots_used = len(selected)
        core_ratio, adjacent_ratio, wildcard_ratio = 1.0, 0.0, 0.0

    else:
        # ── 3-WAY CONTROLLED VARIETY COMPOSITION ────────────────────────────
        # Allocate slots across three tiers based on the user's exploration
        # preference (exploration_weight drifts from 0.5 based on swipe history):
        #
        #   core     (~75%) — matches selected genres exactly
        #   adjacent (~17%) — thematically related genres (curated ADJACENT_GENRES)
        #   wildcard (~8%)  — everything else, true exploration
        #
        # Variety cards are spaced evenly through the core so the user sees
        # a regular rhythm (e.g. C C C V C C C V) rather than 90 core then
        # a cluster of random titles at the end.
        core_ratio, adjacent_ratio, wildcard_ratio = _exploration_ratios(user)

        # ── Thin-pool mode ────────────────────────────────────────────────────
        # When the core genre has very few titles (niche genres like Anime, Talk,
        # News, Western, etc.), the shortfall would normally flow to wildcard,
        # giving users 70-80% truly-random content.  Instead we fill the gap
        # with adjacent titles so the feed stays on-topic.
        #
        # Threshold: < 30 primary-genre titles in the filtered pool.
        # Below this we use ALL available core, then max out adjacent, and only
        # then allow wildcard up to its normal ratio share.
        _confident = _confidence_tier(user) in ("confident", "strongly_personalised")
        if len(core_pool) < POOL_THIN_THRESHOLD and not _confident:
            # Thin-pool rescue (niche genres like Anime/Talk/News for users still
            # establishing intent): use every core title, fill the rest adjacent.
            # NOT applied to confident users — for them a depleted core pool means
            # cooldown has rightly exhausted the genre, and dumping the last few
            # same-genre titles would re-trap them.  They fall through to the
            # proportional path, where the variety floor caps core and the ample
            # adjacent/wildcard pools (same-feeling + discovery) fill the feed.
            core_target     = len(core_pool)   # use every available core title
            wildcard_target = min(len(wildcard_pool), max(0, round(limit * wildcard_ratio)))
            adjacent_target = min(len(adjacent_pool), limit - core_target - wildcard_target)
        else:
            # Variety-floor composition.  Core is capped at its ratio share (so a
            # large pool can't re-trap the user in one genre).  Whatever the feed
            # needs beyond core is filled by ADJACENT first — same-feeling
            # broadening — while a wildcard reserve keeps a 15-25% discovery band
            # so confident users always get genuine discovery.  When the core
            # pool is depleted by cooldown (a matured user who has swiped through
            # the genre) the freed slots flow to adjacent, not a wall of random
            # wildcard, so the feed still "feels like them" while broadening.
            core_target  = min(len(core_pool), max(1, round(limit * core_ratio)))
            remaining    = max(0, limit - core_target)
            wild_reserve = min(len(wildcard_pool), max(0, round(limit * wildcard_ratio)))
            adjacent_target = min(len(adjacent_pool), max(0, remaining - wild_reserve))
            wildcard_target = min(len(wildcard_pool), max(0, remaining - adjacent_target))

        # Band-sample each tier: rotation within quality levels
        # cap: single-genre → 1.0 (no cap); 2 genres → 0.75; 3+ → 0.5
        # This ensures e.g. Documentary+Crime doesn't become 90% Documentary
        core_genre_cap = min(1.0, 1.5 / max(1, len(onboard_genres)))
        # Cold-start even-spread: for the first ~50 swipes of a MULTI-genre user,
        # round-robin core slots across every selected genre so a popular pick
        # (Action) can't starve a niche pick (Horror).  Matured users (≥50
        # interactions) keep the existing band-sampled path — no lock-in.
        _n_inter = (
            len(user.get("saved") or []) +
            len(user.get("watched") or []) +
            len(user.get("skipped") or []) +
            len(user.get("onboarding_rated") or [])
        )
        if _n_inter < 50 and len(onboard_genres) > 1:
            c_sampled = _coldstart_even_core(core_pool, core_target, onboard_genres, scores)
        else:
            c_sampled = _band_sample(core_pool, core_target)
        core_section = _diversify(c_sampled, core_target, max_per_genre_frac=core_genre_cap)

        a_sampled        = _band_sample(adjacent_pool, adjacent_target * 3) if adjacent_target > 0 else []
        adjacent_section = _diversify(a_sampled, adjacent_target) if adjacent_target > 0 else []

        w_sampled        = _band_sample(wildcard_pool, wildcard_target * 3) if wildcard_target > 0 else []
        wildcard_section = _diversify(w_sampled, wildcard_target) if wildcard_target > 0 else []

        # Mix variety: adjacent BEFORE wildcard (closer-to-intent exploration
        # surfaces earlier than truly-random wildcard).  No shuffle, so the
        # safer adjacent tier always leads the variety stream.
        variety = list(adjacent_section) + list(wildcard_section)
        # Trust head: emit core cards first so the opening of the feed prioritises
        # the user's explicit intent (and high provider confidence) before any
        # exploration.  Capped so the head never consumes the whole feed.
        trust_head = min(TRUST_HEAD, max(0, limit // 2), len(core_section))
        selected = _interleave_variety(core_section, variety, head=trust_head)[:limit]
        # Hard cap legacy content BEFORE anti-repetition passes.
        selected = _age_tier_filter(selected)
        # Anti-repetition: break up long same-feeling (tone) streaks so the user
        # never sees a wall of one mood.  The trust head and the tail are
        # de-streaked *separately*: the head is reordered among its own (all-core)
        # cards so the opening still anchors to the user's intent and no wildcard
        # is ever pulled forward, while the tail is de-streaked across the full
        # core+variety mix.
        _ph = min(trust_head, len(selected))
        # The head stays intent-anchored — only its own same-feeling spacing is
        # applied (no wildcard is ever pulled forward).  The tail gets feeling
        # spacing (the hard guarantee) then best-effort genre-cluster / franchise
        # spacing layered on top without disturbing it (Task #23 Step 5).
        _tail = _break_feeling_streaks(selected[_ph:], max_run=3)
        _tail = _space_clusters(_tail, max_run=2)
        selected = _break_feeling_streaks(selected[:_ph], max_run=3) + _tail
        _feed_head = _ph

        adjacent_ids_set = {m["id"] for m in adjacent_section}
        wildcard_ids_set = {m["id"] for m in wildcard_section}
        core_slots_used     = sum(1 for m in selected if m["id"] not in adjacent_ids_set and m["id"] not in wildcard_ids_set)
        adjacent_slots_used = sum(1 for m in selected if m["id"] in adjacent_ids_set)
        wildcard_slots_used = sum(1 for m in selected if m["id"] in wildcard_ids_set)

    # Feed diversity diagnostics — genre/theme/tone spread + repetition score.
    diversity_debug = _feed_diversity_debug(selected, head=_feed_head)

    # Structured intent audit log — grep for [intent] to trace any feed
    logger.info(
        f"[intent] user={user['user_id']} "
        f"selected={sorted(onboard_genres) if onboard_genres else 'none'} "
        f"pool={len(pool)} "
        f"core={len(core_pool) if onboard_genres else 'n/a'} "
        f"adjacent={len(adjacent_pool)} "
        f"wildcard={len(wildcard_pool)} "
        f"ratios=({core_ratio:.0%}/{adjacent_ratio:.0%}/{wildcard_ratio:.0%}) "
        f"out=(core={core_slots_used} adj={adjacent_slots_used} wild={wildcard_slots_used}) "
        f"low={intent_low}"
    )
    for m in selected:
        slot = ("adjacent" if m["id"] in adjacent_ids_set else
                "wildcard" if m["id"] in wildcard_ids_set else "core")
        if slot != "core":
            _vc = m.get("card") or {}
            logger.debug(
                f"[variety] {slot.upper()} '{m.get('title')}' genres={m.get('genres')} "
                f"tone={_vc.get('tone', '?')} "
                f"tone_guard={'blocked=' + repr(sorted(_tone_blocked)) if _tone_blocked else 'none'} "
                f"exploration_weight={user.get('exploration_weight', 0.5):.2f}"
            )

    # Auto-refill if pool is running low (fire-and-forget)
    if len(pool) < LOW_WATER:
        _schedule_refill(user["user_id"])

    # Build taste profile once — used by every card's reason string
    taste = _taste_profile(user)

    # Provider-confidence distribution across the cards we're about to return.
    provider_confidence_distribution = {"high": 0, "medium": 0, "low": 0}
    for _m in selected:
        provider_confidence_distribution[
            _provider_confidence(_m, _user_subs, _user_region)
        ] += 1

    out = []
    for idx, m in enumerate(selected):
        in_collab  = m["id"] in collab_set
        is_reintro = m["id"] in reintro_eligible and m["id"] in skipped
        slot_type  = ("adjacent" if m["id"] in adjacent_ids_set else
                      "wildcard" if m["id"] in wildcard_ids_set else
                      "core")
        rating     = float(m.get("rating") or 0)
        band       = (
            "excellent" if rating >= 8.0 else
            "good"      if rating >= 7.0 else
            "decent"
        )
        is_wildcard = slot_type == "wildcard"
        is_fallback = (m["id"] in fallback_ids) or is_reintro
        prov_conf   = _provider_confidence(m, _user_subs, _user_region)
        item = dict(m)
        item["reason"] = _reason_for(m, user, in_collab=in_collab, is_reintro=is_reintro, taste=taste)
        item["reason_code"] = _primary_reason_code(m, user, in_collab=in_collab, is_reintro=is_reintro, taste=taste)
        item["match"] = movie_match_pct(m, user)
        item["_signals"] = {
            "match":              item["match"],
            "in_collab":          in_collab,
            "is_reintro":         is_reintro,
            "maturity":           round(maturity, 2),
            "pool_size":          len(pool),
            "taste_history_size": taste.get("history_size", 0),
            "intent_slot":        slot_type,
            "score":              round(scores.get(m["id"], 0.0), 3),
            "rating_band":        band,
            # ── Age & eligibility diagnostics (Task #35) ────────────────
            "year":               m.get("year"),
            "age_tier":           _age_tier(m),
            "age_years":          (current_year - int(m.get("year") or 0)) if m.get("year") else None,
            "classic_exception":  _classic_exception_ok(m, user=user),
            # ── Per-recommendation explainability ───────────────────────────
            "why_shown":          item["reason"],
            "reason_code":        item["reason_code"],
            "is_wildcard":        is_wildcard,
            "is_fallback":        is_fallback,
            "provider_confidence": prov_conf,
        }
        # Availability label so the UI can clearly flag titles that are NOT
        # included with the user's subscriptions (rent/buy or other-service
        # bypass). Purely additive metadata — does not affect ranking or pool.
        # Use the SAME region-resolved provider path as the feed filter so the
        # label is correct outside the default region (never the flat mirror).
        from providers_util import resolve_region_providers
        _res = resolve_region_providers(m, _user_region)
        _av_set = set(_res["available_on"])
        if not _user_subs:
            _availability = "no_subs_selected"
        elif _av_set & _user_subs:
            _availability = "on_subscription"
        elif set(_res["rent_on"]) or set(_res["buy_on"]):
            _availability = "rent_buy"
        else:
            _availability = "other_service"
        item["_signals"]["availability"] = _availability
        item["availability"] = _availability
        if slot_type in ("adjacent", "wildcard"):
            _vcard = m.get("card") or {}
            item["_signals"]["variety_reason"] = (
                f"{slot_type.capitalize()} slot: "
                + ("related to " if slot_type == "adjacent" else "outside ")
                + str(sorted(onboard_genres))
            )
            item["_signals"]["tone_guard"] = {
                "selected_genre":   sorted(onboard_genres),
                "selected_genres":  sorted(onboard_genres),   # back-compat
                "candidate_genre":  m.get("genres"),
                "candidate_genres": m.get("genres"),          # back-compat
                "candidate_tone":   _candidate_tone_group(m),
                "raw_tone":         _vcard.get("tone", "neutral"),
                "blocked_tones":    sorted(_tone_blocked),
                "tone_compatible":  True,
                "rejection_reason": None,
            }
        # First card carries the feed-level meta for easy debugging
        if idx == 0:
            item["_signals"]["feed_meta"] = {
                "selected_genres":         sorted(onboard_genres),
                "adjacent_genres":         sorted(adjacent_genres),
                "eligible_pool_size":      len(pool),
                "pool_total":              len(pool),                          # back-compat
                "core_pool_count":         len(core_pool) if onboard_genres else len(pool),
                "adjacent_pool_count":     len(adjacent_pool),
                "wildcard_pool_count":     len(wildcard_pool),
                "intent_pool_count":       len(core_pool) if onboard_genres else len(pool),  # back-compat
                "fill_pool_count":         len(adjacent_pool) + len(wildcard_pool),          # back-compat
                "core_slots":              core_slots_used,
                "adjacent_slots":          adjacent_slots_used,
                "wildcard_slots":          wildcard_slots_used,
                "intent_slots":            core_slots_used,                    # back-compat
                "fill_slots":              adjacent_slots_used + wildcard_slots_used,  # back-compat
                "exploration_weight":      round(float(user.get("exploration_weight") or 0.5), 3),
                "exploration_ratios":      {
                    "core":     round(core_ratio, 3),
                    "adjacent": round(adjacent_ratio, 3),
                    "wildcard": round(wildcard_ratio, 3),
                },
                "queue_size":              len(selected),
                "intent_low_pool_warning":      intent_low,
                "subscription_expanded":        subscription_expanded,        # always False in strict mode
                "subscription_expanded_count":  subscription_expanded_count,  # always 0 in strict mode
                "empty_state_reason":           empty_state_reason,
                "fallback_reason":              fallback_reason,
                "provider_match_count":         provider_match_count,
                "provider_rejected_count":      provider_rejected_count,
                "rent_buy_rejected_count":      rent_buy_rejected_count,
                "unavailable_rejected_count":   unavailable_rejected_count,
                "provider_bypass_triggered":    include_other_services or include_rent_buy,
                "tone_guard_active":            bool(_tone_blocked) or bool(tone_rejected_doc_continuity),
                "tone_guard_blocked":           sorted(_tone_blocked),
                "tone_guard_relaxed":           sorted(_tone_relaxed),
                "tone_rejected_adjacent":       tone_rejected_adjacent,
                "tone_rejected_wildcard":       tone_rejected_wildcard,
                "tone_rejected_doc_continuity": tone_rejected_doc_continuity,
                "tone_debug":                   tone_debug,
                "refill_count":                 _REFILL_COUNT.get(user.get("user_id", ""), 0),
                "shown_excluded":               len(cooldown_set),
                "recently_shown_excluded":      len(cooldown_set),   # back-compat
                "permanently_excluded":         len(permanently_seen),
                "cooldown_hours":               RECENTLY_SHOWN_COOLDOWN_HRS,
                "tracking_max":                 RECENTLY_SHOWN_MAX,
                # ── Final-polish diagnostics ────────────────────────────────
                "pool_before_filters":          pool_before_filters,
                "pool_after_filters":           pool_after_filters,
                "pool_after_broadening":        len(pool),
                "reality_suppressed_count":     reality_suppressed_count,
                "reality_allowed":              _reality_ok,
                "low_vote_suppressed_count":    low_vote_suppressed_count,
                "genre_match_mode":             genre_match_mode,
                "fallback_count":               len(fallback_ids),
                "provider_confidence_distribution": provider_confidence_distribution,
                "rejection_debug":              rejection_debug,
                # ── Feed diversity debug (genre/theme/tone spread + repetition)
                "diversity":                    diversity_debug,
                # ── Age-tier distribution in served feed (Task #35) ─────────
                "age_tier_distribution":          {
                    "A": sum(1 for m in selected if _age_tier(m) == "A"),
                    "B": sum(1 for m in selected if _age_tier(m) == "B"),
                    "C": sum(1 for m in selected if _age_tier(m) == "C"),
                    "unknown": sum(1 for m in selected if _age_tier(m) is None),
                },
                "classic_exception_count":      sum(1 for m in selected if _classic_exception_ok(m, user=user)),
                "oldest_year_in_feed":          min((int(m.get("year") or 9999) for m in selected), default=None),
                "youngest_year_in_feed":       max((int(m.get("year") or 0) for m in selected), default=None),
            }
        out.append(item)

    # ── Pre-floor (classic) admission audit log ─────────────────────────────
    # Every pre-RELEASE_YEAR_FLOOR title that made it into a served feed gets a
    # structured log line: id, year, rank, score, quality, tier, eligibility,
    # source pool, reason code, fallback path, classic affinity, admitting
    # rule. If an old title ever appears wrongly (like Jaws 2 did), this line
    # is the audit trail showing exactly which rule admitted it.
    from core import RELEASE_YEAR_FLOOR, classic_admission_reason
    for _rank, _it in enumerate(out):
        _yr = int(_it.get("year") or 0)
        if not _yr or _yr >= RELEASE_YEAR_FLOOR:
            continue
        _reason = classic_admission_reason(_it, user=user)
        _sig = _it.get("_signals") or {}
        logger.info(
            "[classic-audit] user=%s movie_id=%s title=%r year=%s rank=%d "
            "score=%s quality_score=%s quality_tier=%s age_tier=%s eligible=%s "
            "source_pool=%s reason_code=%s fallback_path=%s "
            "classic_affinity=%s admitting_rule=%s",
            user.get("user_id"), _it.get("id"), _it.get("title"), _yr, _rank,
            _sig.get("score"), _reason.get("quality_score"),
            (_it.get("card") or {}).get("quality_tier") or _it.get("quality_tier"),
            _sig.get("age_tier"), _reason.get("eligible"),
            _sig.get("intent_slot"),
            _reason.get("reason_code"),
            "fallback" if _sig.get("is_fallback") else "normal",
            _reason.get("classic_affinity"), _reason.get("tier"),
        )
        if not _reason.get("eligible"):
            logger.error(
                "[classic-audit] INELIGIBLE OLD TITLE SERVED: %s (%s, %s) — "
                "gate bypass bug, investigate source_pool=%s fallback=%s",
                _it.get("title"), _it.get("id"), _yr,
                _sig.get("intent_slot"), _sig.get("is_fallback"),
            )

    # Track shown asynchronously (don't await — stays out of the hot path)
    _schedule_record_shown(user["user_id"], [m["id"] for m in out])
    # Impression logging (Task #38): record exact feed + generate impression_id
    # so every subsequent user action can link deterministically to this feed.
    impression_id = _schedule_log_impressions(user["user_id"], out)
    # Thread impression_id into every card so the frontend can echo it back
    for it in out:
        it["impression_id"] = impression_id

    return out


# ---------------------------------------------------------------------------
# Recently-shown tracker
# ---------------------------------------------------------------------------

async def _record_shown(user_id: str, ids: Iterable[str]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    new_entries = [{"id": i, "at": now_iso} for i in ids]
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "recently_shown": 1})
    existing = (user or {}).get("recently_shown") or []
    # Drop existing entries for the same ids, then prepend new ones
    new_ids = {e["id"] for e in new_entries}
    merged = new_entries + [e for e in existing if e.get("id") not in new_ids]
    merged = merged[:RECENTLY_SHOWN_MAX]
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"recently_shown": merged}},
    )


def _schedule_record_shown(user_id: str, ids: list[str]) -> None:
    if not ids:
        return
    try:
        asyncio.create_task(_record_shown(user_id, ids))
    except RuntimeError:
        # No running loop (rare — background context). Skip silently.
        pass


# ---------------------------------------------------------------------------
# First-run taste-profile backfill (Task #23 Step 3)
# ---------------------------------------------------------------------------

async def _persist_taste_backfill(user_id: str, profile: dict) -> None:
    """Persist a derived taste snapshot for a user who lacks one.

    Guarded on ``taste_profile`` being absent so a concurrent swipe (which writes
    a fresh profile) is never clobbered by this best-effort backfill.  Failures
    are swallowed: the snapshot is a denormalised read surface, never required
    for a feed to render."""
    try:
        await db.users.update_one(
            # Treat absent OR explicit-null as "missing" (legacy docs may carry a
            # null), but never clobber a real profile written by a concurrent swipe.
            {"user_id": user_id,
             "$or": [{"taste_profile": {"$exists": False}}, {"taste_profile": None}]},
            {"$set": {"taste_profile": profile}},
        )
    except Exception:
        pass


def _schedule_taste_backfill(user_id: str, profile: dict) -> None:
    try:
        asyncio.create_task(_persist_taste_backfill(user_id, profile))
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Impression logging (recording only — Task #23 Step 10)
# ---------------------------------------------------------------------------

IMPRESSIONS_MAX = 5000   # safety cap on retained impression rows per user


async def _log_impressions(user_id: str, items: list, impression_id: str) -> None:
    """Record the exact feed served — one row per card with its rank, slot,
    reason_code, score, title, and feed-level context.

    The impression_id is pre-generated by the caller and threaded back into
    the feed response so every user action can link deterministically to the
    specific recommendation that produced it.

    Recording only: never read back into ranking here, purely a substrate for
    diagnostics and future offline learning.  Failures are swallowed so
    logging can never break a feed response."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []
        feed_size = len(items)
        for rank, it in enumerate(items):
            sig = it.get("_signals") or {}
            rows.append({
                "id":          it.get("id"),
                "title":       it.get("title"),
                "rank":        rank,
                "slot":        sig.get("intent_slot"),
                "reason_code": it.get("reason_code"),
                "score":       sig.get("score"),
                "served_at":   now_iso,
                "feed_size":   feed_size,
            })
        if not rows:
            return
        await db.impressions.insert_one({
            "user_id":       user_id,
            "impression_id": impression_id,
            "at":            now_iso,
            "count":         feed_size,
            "items":         rows,
        })
        # Trim oldest impression docs beyond the cap (best-effort housekeeping).
        total = await db.impressions.count_documents({"user_id": user_id})
        if total > IMPRESSIONS_MAX:
            stale = db.impressions.find(
                {"user_id": user_id}, {"_id": 1}
            ).sort("at", 1).limit(total - IMPRESSIONS_MAX)
            old_ids = [d["_id"] async for d in stale]
            if old_ids:
                await db.impressions.delete_many({"_id": {"$in": old_ids}})
    except Exception:
        # Recording only — never propagate.
        pass


def _schedule_log_impressions(user_id: str, items: list) -> str:
    """Fire-and-forget impression logging.  Returns the impression_id immediately
    (before the DB write completes) so the caller can thread it into the response."""
    if not items:
        return ""
    impression_id = str(uuid.uuid4())
    try:
        asyncio.create_task(_log_impressions(user_id, items, impression_id))
    except RuntimeError:
        pass
    return impression_id


# ---------------------------------------------------------------------------
# Background refill
# ---------------------------------------------------------------------------

async def _do_refill(user_id: str) -> None:
    """Expand the catalog when the pool runs low — uses the fast bulk importer."""
    _REFILL_COUNT[user_id] = _REFILL_COUNT.get(user_id, 0) + 1
    try:
        from core import db, load_catalog_from_db
        from catalog_import import bulk_import_catalog, enrich_providers_top
        before = len(get_catalog())
        result = await bulk_import_catalog(db, pages_general=5, pages_genre=3)
        await load_catalog_from_db()
        after = len(get_catalog())
        logger.info(
            f"Pool refill for {user_id}: {before} → {after} titles "
            f"({result['unique']} imported from TMDB)"
        )
        # Enrich providers for the new batch in the background
        asyncio.create_task(enrich_providers_top(db, limit=300, region="GB"))
    except Exception as e:
        logger.warning(f"Pool refill failed for {user_id}: {e}")
    finally:
        _REFILL_LOCK.pop(user_id, None)


def _schedule_refill(user_id: str) -> None:
    if user_id in _REFILL_LOCK:
        return
    try:
        task = asyncio.create_task(_do_refill(user_id))
        _REFILL_LOCK[user_id] = task
    except RuntimeError:
        pass


async def engagement_summary(user: dict) -> dict:
    """Lightweight transparency endpoint — what does the engine know about me?"""
    total_actions = await db.user_actions.count_documents({"user_id": user["user_id"]})
    by_action_pipeline = [
        {"$match": {"user_id": user["user_id"]}},
        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
    ]
    by_action: dict = {}
    async for row in db.user_actions.aggregate(by_action_pipeline):
        by_action[row["_id"]] = row["count"]
    gw = user.get("genre_weights") or {}
    top_genres = sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:5]
    taste = _taste_profile(user)

    # Expose all learned weight dimensions so the frontend can show a rich
    # "what the engine knows about you" transparency card.
    tw  = user.get("tone_weights")   or {}
    pw  = user.get("pacing_weights") or {}
    thw = user.get("theme_weights")  or {}

    return {
        "maturity": round(_maturity(user), 2),
        "total_interactions": total_actions,
        "by_action": by_action,
        "top_learned_genres":  [{"genre": g,  "weight": round(v, 3)} for g, v in top_genres],
        "top_learned_tones":   [{"tone":  t,  "weight": round(v, 3)}
                                 for t, v in sorted(tw.items(),  key=lambda x: x[1], reverse=True)[:3]],
        "top_learned_pacings": [{"pacing": p, "weight": round(v, 3)}
                                 for p, v in sorted(pw.items(),  key=lambda x: x[1], reverse=True)[:3]],
        "top_learned_themes":  [{"theme": t,  "weight": round(v, 3)}
                                 for t, v in sorted(thw.items(), key=lambda x: x[1], reverse=True)[:5]],
        "type_weights":   user.get("type_weights") or {},
        "watchlist_size": len(user.get("saved")    or []),
        "watched_count":  len(user.get("watched")  or []),
        "taste_profile":  taste,
    }
