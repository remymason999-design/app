"""Offline, no-write comparison of two onboarding-trained Discover feeds.

Run from ``backend`` with the application's normal environment:
    PYTHONPATH=. python scripts/onboarding_discover_report.py

This exercises the actual ``build_feed`` composition/scoring path against the
loaded in-memory catalogue while replacing database-backed enrichment and all
asynchronous writes with no-ops.  It never creates user, action, impression, or
catalogue records.
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

import core
import engine
import global_learning
from content_cards import attach_cards
from routers.onboarding import _pick_diverse_titles
from taste import effective_weight_map, onboarding_learning_inc


async def _empty_set(*_args, **_kwargs):
    return set()


async def _empty_map(*_args, **_kwargs):
    return {}


def _add_inc(target: dict, inc: dict) -> None:
    for dotted, value in inc.items():
        field, key = dotted.split(".", 1)
        target.setdefault(field, {})
        target[field][key] = target[field].get(key, 0) + value


def _trained_user(user_id: str, genres: list[str], positive_titles: set[str]) -> tuple[dict, list[dict], set[str]]:
    user = {
        "user_id": user_id,
        "genres": genres,
        "subscriptions": [],
        "content_type": "both",
        "onboarding_rated": [],
        "saved": [],
        "watched": [],
        "skipped": [],
        "post_onboarding_interactions": 0,
        # Explicit selected genres remain a non-decaying stated preference.
        "genre_weights": {genre: 1.0 for genre in genres},
    }
    deck = _pick_diverse_titles(user, n=10)
    for movie in deck:
        # Deliberate, selective training—not a blanket like for every chosen
        # genre. Unselected cards are explicit skips (zero affinity learning).
        rating = 4.0 if movie["title"] in positive_titles else 0.0
        _add_inc(user, onboarding_learning_inc(movie, rating))
        user["onboarding_rated"].append(movie["id"])
    return user, deck, positive_titles


def _score_for_profile(movie: dict, user: dict) -> float:
    weights = effective_weight_map(user, "genre_weights")
    learned_top = {
        genre for genre, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True)[:3]
        if weight >= 2
    }
    return engine._hybrid_score(
        movie, user, maturity=engine._maturity(user),
        neg_maturity=engine._neg_maturity(user), collab_set=set(),
        learned_top_genres=learned_top, current_year=datetime.now(timezone.utc).year,
    )


def _selected_genres_only_control() -> tuple[dict, list[dict], set[str]]:
    """Counterfactual: same selected genres as A, without title interactions."""
    genres = ["Crime", "Thriller", "Mystery"]
    return ({
        "user_id": "offline-onboarding-a-control",
        "genres": genres, "subscriptions": [], "content_type": "both",
        "onboarding_rated": [], "saved": [], "watched": [], "skipped": [],
        "post_onboarding_interactions": 0,
        "genre_weights": {genre: 1.0 for genre in genres},
    }, [], set())


async def main() -> None:
    # Attach cards in memory only, then replace every write / database-dependent
    # enrichment path before invoking the real Discover feed builder.
    # This is a read-only load rather than core.load_catalog_from_db(), because
    # that production helper may persist card-enrichment deltas.
    docs = await core.db.movies_cache.find({}, {"_id": 0}).to_list(length=10000)
    if docs:
        doc_keys = {(m.get("title", "").lower().strip(), m.get("year")) for m in docs}
        core.CATALOG = docs + [
            m for m in core.SEED_MOVIES
            if (m.get("title", "").lower().strip(), m.get("year")) not in doc_keys
        ]
    attach_cards(engine.get_catalog())
    engine._collaborative_boost_set = _empty_set
    engine._eligible_skip_reintros = _empty_set
    engine._schedule_record_shown = lambda *_args, **_kwargs: None
    engine._schedule_log_impressions = lambda *_args, **_kwargs: "offline"
    engine._schedule_taste_backfill = lambda *_args, **_kwargs: None
    engine._schedule_refill = lambda *_args, **_kwargs: None
    global_learning.compute_new_user_boost = _empty_map
    global_learning.get_community_quality_scores = _empty_map
    global_learning.get_discovery_scores = _empty_map
    global_learning.get_self_cleaning_flags = _empty_set

    profiles = {
        "A_crime_thriller_mystery": _trained_user(
            "offline-onboarding-a", ["Crime", "Thriller", "Mystery"],
            {"Obsession", "The Runner", "The Mentalist",
             "Law & Order: Special Victims Unit", "Breaking Bad"},
        ),
        "B_comedy_romance_family": _trained_user(
            "offline-onboarding-b", ["Comedy", "Romance", "Family"],
            {"Clash of the Thundermans", "The Simpsons", "Ted Lasso",
             "Young Sheldon", "Titanic"},
        ),
        "A_selected_genres_only_control": _selected_genres_only_control(),
    }
    result, feeds = {}, {}
    for name, (user, deck, positive_titles) in profiles.items():
        feed = await engine.build_feed(user, limit=30)
        feeds[name] = feed
        result[name] = {
            "deck": [{
                "title": m["title"], "genres": m.get("genres"),
                "response": "like" if m["title"] in positive_titles else "skip",
            } for m in deck],
            "first_20": [
                {
                    "title": m["title"],
                    "genres": m.get("genres"),
                    "reason": m.get("reason"),
                    "score": round(float((m.get("_signals") or {}).get("score") or 0), 3),
                }
                for m in feed[:20]
            ],
        }
    a_name = "A_crime_thriller_mystery"
    b_name = "B_comedy_romance_family"
    control_name = "A_selected_genres_only_control"
    a_user = profiles[a_name][0]
    b_user = profiles[b_name][0]
    comparison = (feeds[a_name][:5] + feeds[b_name][:5])
    result["counterfactual_score_comparison"] = [
        {
            "title": movie["title"],
            "score_as_A": round(_score_for_profile(movie, a_user), 3),
            "score_as_B": round(_score_for_profile(movie, b_user), 3),
        }
        for movie in comparison
    ]
    a_titles = [movie["title"] for movie in feeds[a_name][:20]]
    control_titles = [movie["title"] for movie in feeds[control_name][:20]]
    result["same_genre_control_comparison"] = {
        "trained_only": [title for title in a_titles if title not in control_titles],
        "control_only": [title for title in control_titles if title not in a_titles],
        "shared_count": len(set(a_titles) & set(control_titles)),
    }
    report = json.dumps(result, indent=2)
    report_path = Path(__file__).resolve().parents[1] / "reports" / "onboarding_discover_report.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())