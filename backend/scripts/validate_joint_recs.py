#!/usr/bin/env python3
"""Dry-run validation for the "For you both" joint recommender (Feature 2).

Runnable:  cd backend && python scripts/validate_joint_recs.py

Builds synthetic user PROFILE PAIRS entirely in memory (NO DB writes) and runs
``sharing._shared_recommendations`` against a catalog loaded read-only from
Mongo (falling back to the in-memory seed if Mongo is empty/unreachable).

For each pair it prints, per result: both individual scores, joint score,
reason, shared genres, dislike conflicts, provider availability, plus the
per-pair exclusion counts.
"""
import os
import sys
import asyncio

# Ensure the backend package root is importable when run as `python scripts/...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402
from content_cards import attach_cards  # noqa: E402


async def _load_catalog(limit: int = 400) -> list:
    """Load up to `limit` enriched titles read-only from Mongo (find(), no
    aggregation pipelines), attach cards, and install them as the in-memory
    CATALOG so get_catalog() serves them. Falls back to the seed on any error."""
    try:
        docs = await core.db.movies_cache.find({}, {"_id": 0}).to_list(length=limit)
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"[warn] Mongo unavailable ({type(e).__name__}: {e}); using seed catalog")
        docs = []
    if not docs:
        from movies_seed import SEED_MOVIES
        docs = list(SEED_MOVIES)
        print(f"[info] Using seed catalog: {len(docs)} titles")
    else:
        print(f"[info] Loaded {len(docs)} titles from movies_cache (read-only)")
    attach_cards(docs)
    core.CATALOG = docs
    return docs


def _user(name, *, genres, subs, region="GB", genre_weights=None, tone_weights=None,
          excluded_genres=None, show_anime_asian=True, saved=None, hard_skips=None,
          watched_feedback=None):
    """Construct a synthetic user dict in memory (never persisted)."""
    return {
        "user_id": f"synthetic_{name}",
        "name": name,
        "country": region,
        "genres": list(genres),
        "subscriptions": list(subs),
        "genre_weights": dict(genre_weights or {}),
        "tone_weights": dict(tone_weights or {}),
        "excluded_genres": list(excluded_genres or []),
        "show_anime_asian": show_anime_asian,
        "show_international": True,
        "saved": list(saved or []),
        "watched": [],
        "skipped": [],
        "hard_skips": list(hard_skips or []),
        "watched_feedback": dict(watched_feedback or {}),
        "onboarding_rated": [f"seed{i}" for i in range(20)],  # give some maturity
    }


def _build_pairs():
    """Five synthetic profile pairs covering the required scenarios."""
    pairs = []

    # 1. crime/thriller  +  crime/drama  (strong overlap on Crime)
    a = _user("Alex_crime_thriller", genres=["Crime", "Thriller"],
              subs=["netflix", "prime_video"],
              genre_weights={"Crime": 6.0, "Thriller": 5.0, "Romance": -2.0})
    b = _user("Bella_crime_drama", genres=["Crime", "Drama"],
              subs=["netflix", "hbo_max"],
              genre_weights={"Crime": 5.0, "Drama": 4.0, "Horror": -3.0})
    pairs.append(("crime/thriller + crime/drama", a, b))

    # 2. Marvel-action  +  historical-drama  (low overlap)
    a = _user("Carlos_marvel_action", genres=["Action", "Adventure", "Sci-Fi"],
              subs=["disney_plus", "netflix"],
              genre_weights={"Action": 7.0, "Adventure": 5.0, "Sci-Fi": 4.0, "Drama": -1.0})
    b = _user("Dana_historical_drama", genres=["Drama", "Romance"],
              subs=["netflix", "apple_tv"],
              genre_weights={"Drama": 6.0, "Romance": 4.0, "Action": -3.5})
    pairs.append(("Marvel-action + historical-drama", a, b))

    # 3. animation  +  adult-thriller  (opposing tone/content)
    a = _user("Evan_animation", genres=["Animation", "Adventure", "Fantasy"],
              subs=["disney_plus"],
              genre_weights={"Animation": 6.0, "Adventure": 4.0, "Fantasy": 3.0,
                             "Horror": -4.0, "Thriller": -2.0})
    b = _user("Fiona_adult_thriller", genres=["Thriller", "Horror", "Crime"],
              subs=["netflix", "prime_video"],
              genre_weights={"Thriller": 6.0, "Horror": 5.0, "Crime": 4.0,
                             "Animation": -3.0, "Family": -3.0})
    pairs.append(("animation + adult-thriller", a, b))

    # 4. near-identical tastes
    a = _user("Gus_scifi", genres=["Sci-Fi", "Action", "Adventure"],
              subs=["netflix", "hbo_max"],
              genre_weights={"Sci-Fi": 6.0, "Action": 5.0, "Adventure": 4.0})
    b = _user("Hana_scifi", genres=["Sci-Fi", "Action", "Adventure"],
              subs=["netflix", "hbo_max"],
              genre_weights={"Sci-Fi": 5.5, "Action": 5.0, "Adventure": 4.5})
    pairs.append(("near-identical", a, b))

    # 5. highly-opposing tastes + explicit conflicts (hard skips, excludes)
    a = _user("Ivan_horror", genres=["Horror", "Thriller"],
              subs=["prime_video"],
              genre_weights={"Horror": 7.0, "Thriller": 5.0, "Romance": -5.0,
                             "Comedy": -3.0},
              hard_skips=["m_barbie"],
              excluded_genres=["Romance"])
    b = _user("Jaya_romcom", genres=["Romance", "Comedy"],
              subs=["disney_plus"],
              genre_weights={"Romance": 7.0, "Comedy": 6.0, "Horror": -6.0,
                             "Thriller": -4.0},
              excluded_genres=["Horror"],
              watched_feedback={"m_oppenheimer": {"sentiment": "disliked", "completed": True}})
    pairs.append(("highly-opposing", a, b))

    return pairs


def _run():
    from sharing import _shared_recommendations, _has_dislike_conflict, _can_watch

    pairs = _build_pairs()
    for label, a, b in pairs:
        print("\n" + "=" * 78)
        print(f"PAIR: {label}")
        print(f"  {a['name']:<24} genres={a['genres']} subs={a['subscriptions']}")
        print(f"  {b['name']:<24} genres={b['genres']} subs={b['subscriptions']}")
        counts: dict = {}
        recs = _shared_recommendations(a, b, limit=6, debug_counts=counts)
        print(f"  exclusion counts: {counts}")
        if not recs:
            print("  (no joint recommendations survived exclusions)")
            continue
        for i, r in enumerate(recs, 1):
            m = next((x for x in core.get_catalog() if x["id"] == r["id"]), {})
            conflict = _has_dislike_conflict(m, a, b) if m else False
            avail = {
                a["name"]: _can_watch(m, a) if m else None,
                b["name"]: _can_watch(m, b) if m else None,
            }
            print(f"  [{i}] {r['title'][:40]:<40} joint={r['joint_score']:>7.2f}  "
                  f"a={r['score_a']:>7.2f}  b={r['score_b']:>7.2f}")
            print(f"      reason: {r['reason']}")
            print(f"      shared_genres={r['shared_genres']}  conflict={conflict}  "
                  f"available={avail}")


async def _main():
    await _load_catalog(limit=400)
    _run()


if __name__ == "__main__":
    asyncio.run(_main())
