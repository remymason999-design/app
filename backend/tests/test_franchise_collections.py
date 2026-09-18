import asyncio

from cast_backfill import _fetch_extras
from catalog_import import _catalog_update_document, _light_enrich
from content_cards import build_card, card_similarity, franchise_identity, franchise_matches
from engine import _primary_reason_code, _reason_for, _space_clusters


def _movie(mid, collection_id=None, collection_name=None, genre="Action"):
    movie = {
        "id": mid,
        "type": "movie",
        "genres": [genre],
        "overview": "A sequel adventure.",
        "runtime": 100,
        "vote_count": 100,
        "collection_id": collection_id,
        "collection_name": collection_name,
    }
    movie["card"] = build_card(movie)
    return movie


def test_build_card_keeps_collection_id_and_display_name():
    card = build_card(_movie("one", 1241, "Harry Potter Collection"))

    assert card["franchise"] == {
        "id": 1241,
        "name": "Harry Potter Collection",
    }
    assert franchise_identity(card["franchise"]) == "tmdb:1241"


def test_catalog_import_retains_collection_when_payload_includes_it():
    movie = _light_enrich(
        {
            "id": 1,
            "title": "A Sequel",
            "release_date": "2020-01-01",
            "poster_path": "/poster.jpg",
            "overview": "A sequel adventure.",
            "vote_count": 10,
            "belongs_to_collection": {
                "id": 1241,
                "name": "Harry Potter Collection",
            },
        },
        "movie",
    )

    assert movie["collection_id"] == 1241
    assert movie["collection_name"] == "Harry Potter Collection"
    update = _catalog_update_document(movie)
    assert update["$set"]["collection_id"] == 1241
    assert update["$set"]["collection_name"] == "Harry Potter Collection"
    assert "collection_id" not in update["$setOnInsert"]
    assert "collection_name" not in update["$setOnInsert"]


def test_detail_backfill_persists_collection_identity():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "belongs_to_collection": {
                    "id": 1241,
                    "name": "Harry Potter Collection",
                },
                "credits": {},
                "keywords": {},
                "videos": {},
                "alternative_titles": {},
            }

    class Client:
        async def get(self, *args, **kwargs):
            return Response()

    extras = asyncio.run(_fetch_extras(Client(), "movie", 1))

    assert extras["collection_id"] == 1241
    assert extras["collection_name"] == "Harry Potter Collection"
    assert extras["metadata_version"] == 5


def test_franchise_spacing_uses_collection_id_even_when_names_differ():
    items = [
        _movie("a", 99, "Saga Collection"),
        _movie("b", 99, "Saga Collection"),
        _movie("c", 99, "Localized Saga Name"),
        _movie("separator", 100, "Other Collection", genre="Sci-Fi"),
    ]

    spaced = _space_clusters(items, max_run=2)

    assert [m["id"] for m in spaced] == ["a", "b", "separator", "c"]
    assert sorted(m["id"] for m in spaced) == sorted(m["id"] for m in items)


def test_franchise_similarity_uses_id_when_names_differ():
    first = _movie("a", 99, "Saga Collection")["card"]
    localized = _movie("b", 99, "Localized Saga Name")["card"]
    unrelated = _movie("c", 100, "Other Collection")["card"]

    assert card_similarity(first, localized) > card_similarity(first, unrelated)


def test_mixed_legacy_and_id_franchises_fall_back_to_name():
    current = {"id": 99, "name": "Saga Collection"}
    legacy = " saga collection "
    name_only = {"id": None, "name": "Saga Collection"}

    assert franchise_matches(current, legacy)
    assert franchise_matches(current, name_only)

    base = _movie("a", 99, "Saga Collection")["card"]
    mixed = dict(_movie("b", None, None)["card"], franchise=legacy)
    unrelated = _movie("c", 100, "Other Collection")["card"]
    assert card_similarity(base, mixed) > card_similarity(base, unrelated)


def test_mixed_legacy_and_id_franchises_are_spaced():
    items = [
        _movie("a", 99, "Saga Collection"),
        dict(_movie("b"), card={**_movie("b")["card"], "franchise": "Saga Collection"}),
        dict(_movie("c"), card={**_movie("c")["card"], "franchise": {"id": None, "name": "Saga Collection"}}),
        _movie("separator", 100, "Other Collection", genre="Sci-Fi"),
    ]

    spaced = _space_clusters(items, max_run=2)
    assert [m["id"] for m in spaced] == ["a", "b", "separator", "c"]


def test_collection_reason_and_code_use_display_name():
    movie = _movie("one", 1241, "Harry Potter Collection")
    user = {"genres": [], "genre_weights": {}}

    assert _reason_for(
        movie, user, in_collab=False, is_reintro=False, taste={}
    ) == "Part of the Harry Potter Collection"
    assert _primary_reason_code(
        movie, user, in_collab=False, is_reintro=False, taste={}
    ) == "franchise"


def test_legacy_string_franchise_still_spaces():
    assert franchise_identity("  Saga Collection  ") == (
        "name:saga collection"
    )