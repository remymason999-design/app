"""Deterministic onboarding selection and signal-strength regressions."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from routers import onboarding
from routers import user as user_router
from routers.user import _post_onboarding_count_update
from core import PreferencesIn
from server import _legacy_onboarding_backfill_filter
from engine import CAST_AFFINITY_WEIGHT, _hybrid_score, _maturity, _neg_maturity
from taste import (
    effective_weight_map, onboarding_learning_inc, onboarding_signal_decay,
    taste_learning_inc,
)


def setup_catalog(monkeypatch, genres):
    catalog = [
        {"id": str(i), "title": str(i), "genres": [g], "poster_url": "poster",
         "type": "movie", "rating": 8, "popularity": 100 - i}
        for i, g in enumerate(genres)
    ]
    monkeypatch.setattr(onboarding, "get_catalog", lambda: catalog)
    monkeypatch.setattr(onboarding, "apply_user_filters", lambda items, user: items)
    monkeypatch.setattr(onboarding, "catalog_quality_gate", lambda *a, **kw: True)
    return catalog


def test_short_deck_is_eighty_twenty_selected_and_adjacent(monkeypatch):
    setup_catalog(monkeypatch, ["Action"] * 12 + ["Horror"] * 8 + ["Thriller"] * 8)
    picks = onboarding._pick_diverse_titles({"genres": ["Action", "Horror"]})
    assert len(picks) == 10
    assert sum(bool(set(m["genres"]) & {"Action", "Horror"}) for m in picks) == 8
    assert sum(m["genres"] == ["Thriller"] for m in picks) == 2
    assert len({m["id"] for m in picks}) == 10


def test_thin_genre_supply_fills_without_repeating_seen_titles(monkeypatch):
    setup_catalog(monkeypatch, ["Horror"] * 3 + ["Comedy"] * 10)
    picks = onboarding._pick_diverse_titles({"genres": ["Horror"]}, seen={"0"})
    assert len(picks) == 2
    assert all(m["id"] != "0" for m in picks)
    assert sum(m["genres"] == ["Horror"] for m in picks) == 2
    assert not any(m["genres"] == ["Comedy"] for m in picks)


def test_old_client_limit_is_capped(monkeypatch):
    setup_catalog(monkeypatch, ["Action"] * 20)
    assert len(asyncio.run(onboarding.onboarding_titles({"genres": ["Action"]}, 18))) == 10


def test_onboarding_signals_are_stronger_and_skip_stays_neutral():
    assert onboarding.ONBOARD_WEIGHTS == {"like": 4.0, "dislike": -3.0, "skip": 0}
    movie = {
        "genres": ["Action"], "year": 2000, "runtime": 100,
        "original_language": "en",
        "card": {"tone": "dark", "pacing": "fast", "themes": ["suspense"]},
    }
    assert taste_learning_inc(movie, 4, onboarding=True) == taste_learning_inc(movie, 4)
    assert taste_learning_inc(movie, 0, onboarding=True) == {}
    learnt = onboarding_learning_inc(movie, 4)
    assert learnt["onboarding_genre_weights.Action"] == 4
    assert learnt["onboarding_theme_weights.suspense"] == 1
    assert "genre_weights.Action" not in learnt


def test_onboarding_title_decay_uses_only_genuine_post_onboarding_actions():
    assert onboarding_signal_decay({}) == 1.0
    assert onboarding_signal_decay({"post_onboarding_interactions": 20}) == 1.0
    assert onboarding_signal_decay({"post_onboarding_interactions": 60}) == 0.625
    assert onboarding_signal_decay({"post_onboarding_interactions": 100}) == 0.25
    assert effective_weight_map({
        "genre_weights": {"Crime": 2},
        "onboarding_genre_weights": {"Crime": 4},
        "post_onboarding_interactions": 60,
    }, "genre_weights") == {"Crime": 4.5}


def test_existing_profile_weights_are_unchanged_without_new_source_maps():
    legacy = {"genre_weights": {"Drama": 11.667, "Comedy": -2}}
    assert effective_weight_map(legacy, "genre_weights") == {
        "Drama": 11.667, "Comedy": -2.0,
    }


def test_post_onboarding_decay_counter_is_completed_source_only_and_once_per_title():
    query, update = _post_onboarding_count_update("u", "movie-1")
    assert query == {
        "user_id": "u",
        "onboarding_completed": True,
        "onboarding_genre_weights": {"$exists": True, "$ne": {}},
        "post_onboarding_counted_ids": {"$ne": "movie-1"},
    }
    assert update == {
        "$addToSet": {"post_onboarding_counted_ids": "movie-1"},
        "$inc": {"post_onboarding_interactions": 1},
    }


def test_source_only_metadata_bonus_is_bounded_and_legacy_cast_affinity_is_active():
    movie = {
        "id": "metadata", "genres": ["Crime"], "type": "movie", "year": 2022,
        "runtime": 110, "popularity": 80, "cast_names": ["Actor One"],
        "director_names": ["Director One"], "writer_names": ["Writer One"],
        "card": {"cast": ["Actor One"], "quality_tier": "A", "confidence_score": 1},
    }
    common = {"user_id": "test", "genres": [], "onboarding_rated": ["x"] * 10}
    kwargs = {
        "maturity": _maturity(common), "neg_maturity": _neg_maturity(common),
        "collab_set": set(), "learned_top_genres": set(), "current_year": 2026,
    }
    legacy = {**common, "cast_weights": {"actor one": 9}}
    no_affinity_score = _hybrid_score(movie, common, **kwargs)
    legacy_score = _hybrid_score(movie, legacy, **kwargs)
    assert legacy_score > no_affinity_score
    assert legacy_score - no_affinity_score <= CAST_AFFINITY_WEIGHT
    source = {
        **common,
        "onboarding_cast_weights": {"actor one": 2},
        "onboarding_director_weights": {"director one": 1.6},
        "onboarding_writer_weights": {"writer one": 1.2},
        "onboarding_runtime_weights": {"medium": 1.2},
        "onboarding_popularity_weights": {"popular": 1},
        "onboarding_quality_pref_weights": {"A": 1},
    }
    boosted = _hybrid_score(movie, source, **kwargs)
    assert boosted > legacy_score
    assert boosted - legacy_score < 4  # all source-only metadata terms are capped


def test_legacy_generic_affinities_receive_no_new_onboarding_maturity_uplift():
    movie = {
        "id": "legacy", "genres": ["Crime"], "type": "movie",
        "card": {"tone": "dark", "confidence_score": 1},
    }
    common = {
        "user_id": "legacy", "genres": [], "tone_weights": {"dark": 4},
        "onboarding_rated": ["old"] * 10,
    }
    args = {
        "maturity": 0.25, "neg_maturity": 0.2, "collab_set": set(),
        "learned_top_genres": set(), "current_year": 2026,
    }
    # Empty new maps must be byte-for-byte equivalent to old generic data:
    # the 10 legacy onboarding IDs cannot lift its generic tone contribution.
    assert _hybrid_score(movie, common, **args) == _hybrid_score(
        movie, {**common, "onboarding_tone_weights": {}}, **args
    )


def test_titles_get_has_zero_learning_side_effect(monkeypatch):
    setup_catalog(monkeypatch, ["Crime"] * 12 + ["Thriller"] * 8)
    user = {"genres": ["Crime"], "genre_weights": {"Drama": 2.0}}
    before = deepcopy(user)
    cards = asyncio.run(onboarding.onboarding_titles(user, 10))
    assert cards
    assert user == before


def test_progress_allows_five_or_catalogue_exhaustion(monkeypatch):
    setup_catalog(monkeypatch, ["Crime"] * 12)
    at_five = asyncio.run(onboarding.onboarding_progress({
        "genres": ["Crime"], "onboarding_rated": ["0", "1", "2", "3", "4"],
    }))
    assert at_five["can_finish"] is True
    assert at_five["remaining"] == 5
    at_ten = asyncio.run(onboarding.onboarding_progress({
        "genres": ["Crime"], "onboarding_rated": [str(i) for i in range(10)],
    }))
    assert at_ten["can_finish"] is True
    assert at_ten["remaining"] == 0

    setup_catalog(monkeypatch, [])
    exhausted = asyncio.run(onboarding.onboarding_progress({
        "genres": ["Crime"], "onboarding_rated": [],
    }))
    assert exhausted["can_finish"] is True
    assert exhausted["exhausted"] is True


class _Result:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class _FakeUsers:
    def __init__(self, document):
        self.document = document

    async def update_one(self, query, update):
        protected_id = (query.get("onboarding_rated") or {}).get("$ne")
        if query.get("onboarding_completed", {}).get("$ne") is True and self.document.get("onboarding_completed"):
            return _Result(0)
        if "$expr" in query and len(self.document.get("onboarding_rated") or []) >= 10:
            return _Result(0)
        if protected_id in (self.document.get("onboarding_rated") or []):
            return _Result(0)
        for key, value in update.get("$addToSet", {}).items():
            self.document.setdefault(key, [])
            if value not in self.document[key]:
                self.document[key].append(value)
        for key, value in update.get("$set", {}).items():
            self.document[key] = value
        for dotted, value in update.get("$inc", {}).items():
            field, key = dotted.split(".", 1)
            self.document.setdefault(field, {})
            self.document[field][key] = self.document[field].get(key, 0) + value
        return _Result(1)

    async def find_one(self, query, projection=None):
        return deepcopy(self.document)


class _FakeActions:
    def __init__(self):
        self.rows = []

    async def insert_one(self, row):
        self.rows.append(row)


def test_rate_is_idempotent_and_keeps_onboarding_source_separate(monkeypatch):
    movie = {"id": "m1", "genres": ["Crime"], "type": "movie", "year": 2020, "poster_url": "p",
             "original_language": "en", "card": {"tone": "dark", "themes": ["suspense"]}}
    users = _FakeUsers({"user_id": "u", "onboarding_rated": []})
    actions = _FakeActions()
    monkeypatch.setattr(onboarding, "get_catalog", lambda: [movie])
    monkeypatch.setattr(onboarding, "apply_user_filters", lambda items, user: items)
    monkeypatch.setattr(onboarding, "catalog_quality_gate", lambda *a, **kw: True)
    monkeypatch.setattr(onboarding, "find_movie", lambda _: movie)
    monkeypatch.setattr(onboarding, "db", SimpleNamespace(users=users, user_actions=actions))
    monkeypatch.setattr(onboarding, "invalidate_discover_cache", lambda _: None)
    first = asyncio.run(onboarding.onboarding_rate(
        onboarding.RateIn(movie_id="m1", rating="like"), users.document
    ))
    assert first["ok"] is True
    assert users.document["onboarding_genre_weights"]["Crime"] == 4
    assert users.document["onboarding_completed"] is False
    assert "genre_weights" not in users.document
    second = asyncio.run(onboarding.onboarding_rate(
        onboarding.RateIn(movie_id="m1", rating="like"), users.document
    ))
    assert second["ok"] is True
    assert users.document["onboarding_genre_weights"]["Crime"] == 4
    assert len(actions.rows) == 1


def test_complete_accepts_five_and_is_idempotent(monkeypatch):
    setup_catalog(monkeypatch, ["Crime"] * 12)
    users = _FakeUsers({
        "user_id": "u", "genres": ["Crime"],
        "onboarding_rated": ["0", "1", "2", "3", "4"],
    })
    monkeypatch.setattr(onboarding, "db", SimpleNamespace(users=users))
    monkeypatch.setattr(onboarding, "invalidate_discover_cache", lambda _: None)
    completed = asyncio.run(onboarding.onboarding_complete(users.document))
    assert completed["onboarding_completed"] is True
    first_timestamp = users.document["onboarding_completed_at"]
    again = asyncio.run(onboarding.onboarding_complete(users.document))
    assert again["onboarding_completed_at"] == first_timestamp


def test_rate_rejects_an_eleventh_card(monkeypatch):
    movie = {"id": "m11", "genres": ["Crime"], "type": "movie", "poster_url": "p"}
    monkeypatch.setattr(onboarding, "find_movie", lambda _: movie)
    monkeypatch.setattr(onboarding, "get_catalog", lambda: [movie])
    monkeypatch.setattr(onboarding, "apply_user_filters", lambda items, user: items)
    monkeypatch.setattr(onboarding, "catalog_quality_gate", lambda *a, **kw: True)
    users = _FakeUsers({
        "user_id": "u", "genres": ["Crime"],
        "onboarding_rated": [str(i) for i in range(10)],
    })
    monkeypatch.setattr(onboarding, "db", SimpleNamespace(users=users, user_actions=_FakeActions()))
    with pytest.raises(Exception) as exc:
        asyncio.run(onboarding.onboarding_rate(
            onboarding.RateIn(movie_id="m11", rating="like"),
            users.document,
        ))
    assert getattr(exc.value, "status_code", None) == 400


def test_rate_rejects_a_catalog_title_outside_current_eligible_deck(monkeypatch):
    issued = {"id": "issued", "title": "issued", "genres": ["Crime"], "type": "movie", "poster_url": "p"}
    arbitrary = {"id": "arbitrary", "title": "arbitrary", "genres": ["Crime"], "type": "movie", "poster_url": "p"}
    monkeypatch.setattr(onboarding, "get_catalog", lambda: [issued])
    monkeypatch.setattr(onboarding, "apply_user_filters", lambda items, user: items)
    monkeypatch.setattr(onboarding, "catalog_quality_gate", lambda *a, **kw: True)
    monkeypatch.setattr(onboarding, "find_movie", lambda _: arbitrary)
    with pytest.raises(Exception) as exc:
        asyncio.run(onboarding.onboarding_rate(
            onboarding.RateIn(movie_id="arbitrary", rating="like"),
            {"user_id": "u", "genres": ["Crime"], "onboarding_rated": []},
        ))
    assert getattr(exc.value, "status_code", None) == 400


def test_completed_user_cannot_add_a_new_onboarding_card(monkeypatch):
    movie = {"id": "new", "title": "new", "genres": ["Crime"], "type": "movie", "poster_url": "p"}
    monkeypatch.setattr(onboarding, "find_movie", lambda _: movie)
    with pytest.raises(Exception) as exc:
        asyncio.run(onboarding.onboarding_rate(
            onboarding.RateIn(movie_id="new", rating="like"),
            {"user_id": "u", "onboarding_completed": True, "onboarding_rated": []},
        ))
    assert getattr(exc.value, "status_code", None) == 400


def test_preferences_cannot_bypass_or_reverse_onboarding_completion():
    with pytest.raises(Exception) as start:
        asyncio.run(user_router.set_prefs(
            PreferencesIn(onboarding_completed=True),
            {"user_id": "u", "onboarding_completed": False},
        ))
    assert getattr(start.value, "status_code", None) == 400
    with pytest.raises(Exception) as reverse:
        asyncio.run(user_router.set_prefs(
            PreferencesIn(onboarding_completed=False),
            {"user_id": "u", "onboarding_completed": True},
        ))
    assert getattr(reverse.value, "status_code", None) == 400


def test_restart_backfill_filter_excludes_pending_and_in_progress_users():
    query = _legacy_onboarding_backfill_filter()
    assert query["onboarding_completed"] == {"$exists": False}
    assert query["onboarding_rated"] == {"$exists": False}
    # A blank/pending registration has none of the behavioral/taste evidence
    # required by any legacy branch, even though it has saved/watched/skipped
    # arrays. Source-marked in-progress users are explicitly excluded too.
    assert [next(iter(branch)) for branch in query["$or"][:3]] == [
        "saved.0", "watched.0", "skipped.0",
    ]
    assert query["onboarding_genre_weights"] == {"$exists": False}
    assert query["onboarding_type_weights"] == {"$exists": False}


def test_quality_and_relevance_are_never_relaxed_for_thin_decks(monkeypatch):
    catalog = [
        {"id": "crime", "title": "crime", "genres": ["Crime"], "poster_url": "p",
         "type": "movie", "rating": 8, "popularity": 100},
        {"id": "adjacent", "title": "adjacent", "genres": ["Thriller"], "poster_url": "p",
         "type": "movie", "rating": 8, "popularity": 90},
        {"id": "bad", "title": "bad", "genres": ["Crime"], "poster_url": "p",
         "type": "movie", "rating": 8, "popularity": 99},
        {"id": "unrelated", "title": "unrelated", "genres": ["Comedy"], "poster_url": "p",
         "type": "movie", "rating": 9, "popularity": 1000},
    ]
    monkeypatch.setattr(onboarding, "get_catalog", lambda: catalog)
    monkeypatch.setattr(onboarding, "apply_user_filters", lambda items, user: items)
    monkeypatch.setattr(onboarding, "catalog_quality_gate", lambda movie, **_: movie["id"] != "bad")
    cards = onboarding._pick_diverse_titles({"genres": ["Crime"]}, n=10)
    assert {card["id"] for card in cards} == {"crime", "adjacent"}


def test_selected_genre_deck_softly_prefers_a_different_card_meaning(monkeypatch):
    def title(mid, popularity, tone, themes, franchise=None):
        return {
            "id": mid, "title": mid, "genres": ["Crime"], "type": "tv",
            "poster_url": "p", "rating": 8, "popularity": popularity,
            "card": {
                "tone": tone, "themes": themes, "pacing": "medium",
                "audience_type": "adult", "primary_category": "crime",
                "secondary_categories": [], "franchise": franchise,
                "confidence_score": 1,
            },
        }
    catalog = [
        title("procedural-1", 100, "dark", ["procedural", "investigation"],
              {"id": 77, "name": "Case Files"}),
        title("procedural-2", 99, "dark", ["procedural", "investigation"], "Case Files"),
        title("procedural-3", 97, "dark", ["procedural", "investigation"]),
        title("different-crime", 80, "witty", ["heist", "con"], None),
    ]
    monkeypatch.setattr(onboarding, "get_catalog", lambda: catalog)
    monkeypatch.setattr(onboarding, "apply_user_filters", lambda items, user: items)
    monkeypatch.setattr(onboarding, "catalog_quality_gate", lambda *a, **kw: True)
    cards = onboarding._pick_diverse_titles({"genres": ["Crime"]}, n=2)
    assert {card["id"] for card in cards} == {"procedural-1", "different-crime"}