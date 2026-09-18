"""Genre-matching debug endpoints — backend-only, no UI changes.

GET /api/debug/genre-match?genre=Documentary
GET /api/debug/taste-check?genre=Documentary
GET /api/debug/genre-report        (tests all 18 spec genres)
GET /api/debug/documentary-pipeline (full pipeline-stage report for Documentary)
"""
from __future__ import annotations

import math
from collections import Counter
from fastapi import APIRouter, Depends, Query

from core import get_catalog, require_user, apply_user_filters, movie_matches

router = APIRouter(prefix="/debug", tags=["debug"])

SPEC_GENRES = [
    "Action", "Adventure", "Animation", "Comedy", "Crime",
    "Documentary", "Drama", "Family", "Fantasy", "History",
    "Horror", "Music", "Mystery", "Romance", "Sci-Fi",
    "Thriller", "War", "Western",
]


def _simulate_discover_top20(genre: str, user: dict) -> dict:
    """Score catalog as the engine would for a cold-start user with one genre."""
    catalog = get_catalog()
    test_user = {
        **user,
        "genres": [genre],
        "genre_weights": {},
        "type_weights": {},
        "onboarding_rated": [],
        "saved": [],
        "watched": [],
        "skipped": [],
        "recently_shown": [],
    }
    total = len(catalog)
    filtered = [m for m in catalog if movie_matches(m, test_user)]

    genre_ids = {m["id"] for m in filtered if genre in (m.get("genres") or [])}
    genre_pool = [m for m in filtered if m["id"] in genre_ids]
    non_genre = sorted(
        [m for m in filtered if m["id"] not in genre_ids],
        key=lambda m: m.get("popularity", 0), reverse=True,
    )
    cap_non = max(0, 2000 - len(genre_pool))
    pool = genre_pool + non_genre[:cap_non]

    def _score(m: dict) -> float:
        rating = float(m.get("rating") or 7.0)
        pop = float(m.get("popularity") or 0)
        quality = math.log1p(pop) + (rating / 2.0) * 0.5
        overlap = 1 if genre in (m.get("genres") or []) else 0
        genre_bonus = overlap * 6.0 * 1.1  # matches engine cold-start: max(0.5, 1.1-0.7*0)
        # Documentary popularity-compensation boost (mirrors engine.py — cold-start tier)
        doc_boost = 6.0 if genre == "Documentary" and "Documentary" in (m.get("genres") or []) else 0.0
        jitter = (hash(m["id"]) % 100) / 1000.0
        return quality + genre_bonus + doc_boost + jitter

    pool.sort(key=_score, reverse=True)
    top20 = pool[:20]

    matching = [m for m in top20 if genre in (m.get("genres") or [])]
    pct = len(matching) / len(top20) * 100 if top20 else 0
    genre_breakdown = Counter(g for m in top20 for g in (m.get("genres") or []))

    return {
        "genre": genre,
        "total_catalog": total,
        "pool_after_filters": len(filtered),
        "genre_pool_size": len(genre_pool),
        "top20_genre_match": len(matching),
        "top20_genre_match_pct": round(pct, 1),
        "top20_genre_breakdown": dict(genre_breakdown.most_common(8)),
        "passed_70pct": pct >= 70,
        "sample_matches": [
            {"title": m["title"], "genres": (m.get("genres") or [])[:4]}
            for m in matching[:5]
        ],
    }


def _simulate_taste_check(genre: str, user: dict) -> dict:
    """Test taste-check card selection for a single genre."""
    from routers.onboarding import _pick_diverse_titles

    test_user = {
        **user,
        "genres": [genre],
        "onboarding_rated": [],
        "saved": [],
        "watched": [],
        "skipped": [],
    }
    picks = _pick_diverse_titles(test_user, n=18, seen=set())
    catalog = get_catalog()
    catalog_filtered = apply_user_filters(
        [m for m in catalog if m.get("poster_url")], test_user
    )
    genre_pool_size = sum(1 for m in catalog_filtered if genre in (m.get("genres") or []))

    matching = [m for m in picks if genre in (m.get("genres") or [])]
    pct = len(matching) / len(picks) * 100 if picks else 0
    breakdown = Counter(g for m in picks for g in (m.get("genres") or []))

    return {
        "genre": genre,
        "pool_after_filters": len(catalog_filtered),
        "genre_pool_size": genre_pool_size,
        "cards_total": len(picks),
        "genre_match_count": len(matching),
        "genre_match_pct": round(pct, 1),
        "genre_breakdown": dict(breakdown.most_common(10)),
        "passed_70pct": pct >= 70,
        "cards": [
            {"title": m["title"], "genres": (m.get("genres") or [])[:4]}
            for m in picks
        ],
    }


@router.get("/genre-match")
async def debug_genre_match(
    genre: str = Query(..., description="Genre to test, e.g. Documentary"),
    user: dict = Depends(require_user),
):
    """Simulate Discover top-20 for a cold-start user with one genre selected."""
    return _simulate_discover_top20(genre, user)


@router.get("/taste-check")
async def debug_taste_check(
    genre: str = Query(..., description="Genre to test, e.g. Documentary"),
    user: dict = Depends(require_user),
):
    """Simulate taste-check card selection for one genre."""
    return _simulate_taste_check(genre, user)


@router.get("/genre-report")
async def debug_genre_report(user: dict = Depends(require_user)):
    """Run discover + taste-check simulation for all 18 spec genres and report pass/fail."""
    discover_results = []
    taste_results = []

    for genre in SPEC_GENRES:
        d = _simulate_discover_top20(genre, user)
        discover_results.append({
            "genre": genre,
            "pool": d["pool_after_filters"],
            "genre_pool": d["genre_pool_size"],
            "top20_match_pct": d["top20_genre_match_pct"],
            "passed": d["passed_70pct"],
        })
        t = _simulate_taste_check(genre, user)
        taste_results.append({
            "genre": genre,
            "pool": t["pool_after_filters"],
            "genre_pool": t["genre_pool_size"],
            "match_pct": t["genre_match_pct"],
            "passed": t["passed_70pct"],
        })

    discover_pass = [r["genre"] for r in discover_results if r["passed"]]
    discover_fail = [r["genre"] for r in discover_results if not r["passed"]]
    taste_pass = [r["genre"] for r in taste_results if r["passed"]]
    taste_fail = [r["genre"] for r in taste_results if not r["passed"]]

    return {
        "catalog_size": len(get_catalog()),
        "discover": {
            "passed": discover_pass,
            "failed": discover_fail,
            "details": discover_results,
        },
        "taste_check": {
            "passed": taste_pass,
            "failed": taste_fail,
            "details": taste_results,
        },
        "summary": {
            "discover_pass_rate": f"{len(discover_pass)}/{len(SPEC_GENRES)}",
            "taste_pass_rate": f"{len(taste_pass)}/{len(SPEC_GENRES)}",
        },
    }


@router.get("/genre-pipeline")
async def debug_genre_pipeline(
    genre: str = Query(..., description="Genre to test, e.g. Horror or Western"),
    subscriptions: str = Query(
        "",
        description="Comma-separated subscription ids to simulate, e.g. 'netflix,prime_video'",
    ),
    user: dict = Depends(require_user),
):
    """Full pipeline report for any genre — uses the real build_feed engine.

    Unlike /debug/genre-match (simplified scorer), this calls build_feed
    directly so reported pool sizes, slot counts, and adaptive-cooldown
    behaviour are exact.

    Debug output fields
    -------------------
    core_pool_size          – titles that exactly match the selected genre
    adjacent_pool_size      – thematically related titles (see ADJACENT_GENRES)
    wildcard_pool_size      – all other eligible titles
    cooldown_excluded       – titles suppressed by the 7-day (or adaptive) cooldown
    subscription_limited    – True when cross-sub expansion fired
    subscription_expanded_count – extra titles added from other services
    empty_state_reason      – why the feed might feel thin (subscription_limited,
                               thin_pool, cooldown_exhausted, …)
    refill_count            – background TMDB refills triggered this server session

    Examples
    --------
      /api/debug/genre-pipeline?genre=Horror
      /api/debug/genre-pipeline?genre=Horror&subscriptions=netflix
      /api/debug/genre-pipeline?genre=Western&subscriptions=prime_video
      /api/debug/genre-pipeline?genre=War
    """
    from engine import build_feed
    from core import catalog_quality_gate, get_catalog

    subs = [s.strip() for s in subscriptions.split(",") if s.strip()]
    active_subs = set(subs) if subs else set(user.get("subscriptions") or [])

    test_user = {
        **user,
        "genres": [genre],
        "subscriptions": sorted(active_subs),
        "genre_weights": {genre: 3.0},
        "onboarding_rated": [],
        "saved": [],
        "watched": [],
        "skipped": [],
        "recently_shown": [],
        "exploration_weight": 0.5,
    }

    catalog = get_catalog()
    stage0_total = len(catalog)
    in_catalog   = [m for m in catalog if genre in (m.get("genres") or [])]
    with_poster  = [m for m in in_catalog if m.get("poster_url")]
    after_qg     = [m for m in with_poster if catalog_quality_gate(m)]
    after_subs   = (
        [m for m in after_qg if set(m.get("available_on") or []) & active_subs]
        if active_subs else after_qg
    )

    feed = await build_feed(test_user, limit=100)
    feed_meta: dict = {}
    if feed:
        feed_meta = feed[0].get("_signals", {}).get("feed_meta", {})

    genre_in_feed = [c for c in feed if genre in (c.get("genres") or [])]
    genre_pct = round(len(genre_in_feed) / len(feed) * 100, 1) if feed else 0
    core_sz = feed_meta.get("core_pool_count") or 0

    return {
        "genre":               genre,
        "subscriptions_tested": sorted(active_subs) if active_subs else "none",

        "pipeline_stages": {
            "total_catalog":       {"all": stage0_total,    genre: len(in_catalog)},
            "has_poster":          {"all": len(with_poster), genre: len(with_poster)},
            "quality_gate":        {"all": stage0_total,    genre: len(after_qg)},
            "subscription_filter": {
                "active_subs":    sorted(active_subs) or "none",
                genre:            len(after_subs),
                "reduction":      f"{len(after_qg) - len(after_subs)} titles removed by subscription filter",
            },
        },

        "engine_output": {
            "core_pool_size":            core_sz,
            "adjacent_pool_size":        feed_meta.get("adjacent_pool_count", 0),
            "wildcard_pool_size":        feed_meta.get("wildcard_pool_count", 0),
            "cooldown_excluded":         feed_meta.get("shown_excluded", 0),
            "subscription_limited":      feed_meta.get("subscription_expanded", False),
            "subscription_expanded_count": feed_meta.get("subscription_expanded_count", 0),
            "queue_size":                len(feed),
            "genre_in_queue":            len(genre_in_feed),
            "genre_pct_of_queue":        genre_pct,
            "intent_low_warning":        feed_meta.get("intent_low_pool_warning", False),
            "empty_state_reason":        feed_meta.get("empty_state_reason"),
            "adjacent_genres":           feed_meta.get("adjacent_genres", []),
            "refill_count":              feed_meta.get("refill_count", 0),
        },

        "verdict": {
            "passes_70pct_genre_in_feed": genre_pct >= 70,
            "pool_health": (
                "healthy"  if core_sz >= 60 else
                "thin"     if core_sz >= 15 else
                "critical"
            ),
            "adaptive_cooldown_active": feed_meta.get("shown_excluded", 0) > 0 and core_sz < 60,
        },

        "sample_titles": [
            {
                "title":        c.get("title"),
                "year":         c.get("year"),
                "genres":       c.get("genres"),
                "available_on": c.get("available_on"),
                "slot":         c.get("_signals", {}).get("intent_slot"),
            }
            for c in genre_in_feed[:10]
        ],
    }


@router.get("/documentary-pipeline")
async def debug_documentary_pipeline(
    genre_combo: str = Query(
        "Documentary",
        description="Comma-separated genres to test, e.g. 'Documentary' or 'Documentary,Crime'",
    ),
    user: dict = Depends(require_user),
):
    """Full pipeline-stage report for Documentary (or Documentary + combo genres).

    Shows exactly how many titles survive each filter stage so you can pinpoint
    where Documentary content is being lost.

    Test cases:
      ?genre_combo=Documentary
      ?genre_combo=Documentary,Crime
      ?genre_combo=Documentary,History
      ?genre_combo=Documentary,Music
    """
    from engine import _recently_shown_active

    genres = [g.strip() for g in genre_combo.split(",") if g.strip()]
    if not genres:
        genres = ["Documentary"]

    catalog = get_catalog()

    # Build a synthetic user with only these genres selected
    test_user = {
        **user,
        "genres": genres,
        "genre_weights": {g: 3.0 for g in genres},  # simulate light prior learning
        "onboarding_rated": [],
        "saved": [],
        "watched": [],
        "skipped": [],
        "recently_shown": [],
    }

    excluded = set(test_user.get("excluded_categories") or [])
    subs = set(test_user.get("subscriptions") or [])

    # ── Stage 0: total catalog ───────────────────────────────────────────────
    stage0_total = len(catalog)
    stage0_doc = [m for m in catalog if "Documentary" in (m.get("genres") or [])]

    # ── Stage 1: has poster ──────────────────────────────────────────────────
    stage1 = [m for m in catalog if m.get("poster_url")]
    stage1_doc = [m for m in stage1 if "Documentary" in (m.get("genres") or [])]

    # ── Stage 2: quality gate (catalog_quality_gate) ─────────────────────────
    from core import catalog_quality_gate
    stage2 = [m for m in stage1 if catalog_quality_gate(m)]
    stage2_doc = [m for m in stage2 if "Documentary" in (m.get("genres") or [])]

    # ── Stage 3: subscription filter ────────────────────────────────────────
    if subs:
        stage3 = [
            m for m in stage2
            if set(m.get("available_on") or []) & subs
        ]
    else:
        stage3 = list(stage2)
    stage3_doc = [m for m in stage3 if "Documentary" in (m.get("genres") or [])]

    # ── Stage 4: content-type filter ─────────────────────────────────────────
    ct = test_user.get("content_type")
    if ct and ct != "both":
        stage4 = [m for m in stage3 if m.get("type") == ct]
    else:
        stage4 = list(stage3)
    stage4_doc = [m for m in stage4 if "Documentary" in (m.get("genres") or [])]

    # ── Stage 5: excluded genres filter ──────────────────────────────────────
    ex_genres = set(test_user.get("excluded_genres") or [])
    if ex_genres:
        stage5 = [m for m in stage4 if not (set(m.get("genres") or []) & ex_genres)]
    else:
        stage5 = list(stage4)
    stage5_doc = [m for m in stage5 if "Documentary" in (m.get("genres") or [])]

    # ── Stage 6: genre combo filter (must have ALL requested genres) ─────────
    if len(genres) > 1:
        stage6_doc = [
            m for m in stage5_doc
            if all(g in (m.get("genres") or []) for g in genres)
        ]
    else:
        stage6_doc = list(stage5_doc)

    # ── Stage 7: scoring simulation (top-20) ─────────────────────────────────
    # Use full filtered pool (not just documentary) to show what's competing
    pool = list(stage5)
    genre_set = set(genres)

    def _score(m: dict) -> float:
        rating = float(m.get("rating") or 7.0)
        pop = float(m.get("popularity") or 0)
        quality = math.log1p(pop) * 1.0 + (rating / 2.0) * 0.75
        m_genres = set(m.get("genres") or [])
        onboard_match = 1 if (m_genres & genre_set) else 0
        genre_bonus = onboard_match * 6.0 * 1.1
        # Documentary popularity-compensation boost
        doc_boost = 1.5 if "Documentary" in m_genres and "Documentary" in genre_set else 0.0
        jitter = (hash(m["id"]) % 100) / 1000.0
        return quality + genre_bonus + doc_boost + jitter

    pool.sort(key=_score, reverse=True)
    top20 = pool[:20]
    top20_doc = [m for m in top20 if "Documentary" in (m.get("genres") or [])]
    top20_combo = [
        m for m in top20
        if all(g in (m.get("genres") or []) for g in genres)
    ]

    pct_doc_in_top20 = len(top20_doc) / len(top20) * 100 if top20 else 0
    pct_combo_in_top20 = len(top20_combo) / len(top20) * 100 if top20 else 0
    top20_genre_breakdown = Counter(g for m in top20 for g in (m.get("genres") or []))

    # ── Taste-check simulation ───────────────────────────────────────────────
    taste = _simulate_taste_check("Documentary", user)

    return {
        "test_genres": genres,
        "user_subscriptions": list(subs),
        "user_content_type": ct or "both",

        "pipeline_stages": {
            "stage0_total_catalog":           {"all": stage0_total,        "documentary": len(stage0_doc)},
            "stage1_has_poster":              {"all": len(stage1),          "documentary": len(stage1_doc)},
            "stage2_quality_gate":            {"all": len(stage2),          "documentary": len(stage2_doc)},
            "stage3_subscription_filter":     {"all": len(stage3),          "documentary": len(stage3_doc)},
            "stage4_content_type_filter":     {"all": len(stage4),          "documentary": len(stage4_doc)},
            "stage5_excluded_genres_filter":  {"all": len(stage5),          "documentary": len(stage5_doc)},
            "stage6_combo_genre_match":       {"documentary_with_all_genres": len(stage6_doc)},
        },

        "scoring_top20": {
            "pool_entering_scorer":           len(pool),
            "documentary_in_pool":            len(stage5_doc),
            "documentary_in_top20":           len(top20_doc),
            "combo_match_in_top20":           len(top20_combo),
            "documentary_pct_of_top20":       round(pct_doc_in_top20, 1),
            "combo_match_pct_of_top20":       round(pct_combo_in_top20, 1),
            "passed_70pct_documentary":       pct_doc_in_top20 >= 70,
            "passed_70pct_combo":             pct_combo_in_top20 >= 70,
            "top20_genre_breakdown":          dict(top20_genre_breakdown.most_common(10)),
            "top20_titles": [
                {
                    "title": m["title"],
                    "year": m.get("year"),
                    "genres": m.get("genres") or [],
                    "available_on": m.get("available_on") or [],
                    "is_documentary": "Documentary" in (m.get("genres") or []),
                    "is_combo_match": all(g in (m.get("genres") or []) for g in genres),
                }
                for m in top20
            ],
        },

        "taste_check": {
            "genre_pool_size":     taste["genre_pool_size"],
            "cards_total":         taste["cards_total"],
            "documentary_cards":   taste["genre_match_count"],
            "documentary_pct":     taste["genre_match_pct"],
            "passed_70pct":        taste["passed_70pct"],
            "cards": taste["cards"],
        },

        "catalog_all_documentary_titles": [
            {
                "id": m["id"],
                "title": m["title"],
                "year": m.get("year"),
                "genres": m.get("genres") or [],
                "available_on": m.get("available_on") or [],
                "rating": m.get("rating"),
                "popularity": m.get("popularity"),
                "passes_quality_gate": catalog_quality_gate(m),
                "passes_subscription_filter": (
                    not subs or bool(set(m.get("available_on") or []) & subs)
                ),
            }
            for m in stage0_doc
        ],
    }
