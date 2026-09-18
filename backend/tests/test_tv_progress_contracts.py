import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from progress import (
    episode_key, parse_episode_key, normalize_progress,
    progress_fingerprint, watched_episode_count, completion_metadata,
)


def test_episode_keys_are_stable_and_round_trip():
    assert episode_key(1, 2) == "s01e002"
    assert parse_episode_key("S01E002") == (1, 2)


def test_legacy_cursor_is_preserved_and_canonical_map_is_safe():
    record = normalize_progress({"season": 2, "episode": 4})
    assert record["season"] == 2
    assert record["episodes"] == {}
    assert watched_episode_count(record) == 0


def test_invalid_episode_keys_are_not_accepted():
    record = normalize_progress({"episodes": {"bad": True, "s01e001": True}})
    assert "bad" not in record["episodes"]
    assert watched_episode_count(record) == 1


def test_fingerprint_changes_for_progress_feedback_and_preferences():
    user = {"progress": {}, "watched_feedback": {}, "genres": ["Drama"]}
    first = progress_fingerprint(user)
    user["progress"] = {"tv_1": {"episodes": {"s01e001": {"watched": True}}}}
    assert progress_fingerprint(user) != first


def test_completion_is_unknown_without_season_metadata():
    rec = {"episodes": {"s01e001": {"watched": True, "provenance": "bulk_inferred"}}}
    result = completion_metadata(rec, seasons=[])
    assert result["started"] is True
    assert result["watched_episode_count"] == 1
    assert result["eligible_episode_count"] is None
    assert result["completed"] is None
    assert result["provenance"] == "inferred"


def test_future_episodes_are_excluded_and_runtime_is_measured():
    rec = {"episodes": {
        "s01e001": {"watched": True, "provenance": "explicit"},
        "s01e002": {"watched": True, "provenance": "explicit"},
    }}
    seasons = [{"season_number": 1, "episode_count": 2, "episodes": [
        {"episode_key": "s01e001", "air_date": "2020-01-01", "runtime": 52},
        {"episode_key": "s01e002", "air_date": "2999-01-01", "runtime": 61},
    ]}]
    result = completion_metadata(rec, seasons, runtime=45)
    assert result["eligible_episode_count"] == 1
    assert result["watched_released_episode_count"] == 1
    assert result["completed"] is True
    assert result["eligible_count_provenance"] == "tmdb_release_dates"
    assert result["measured_runtime_minutes"] == 113
    assert result["measured_runtime_episode_count"] == 2
    assert result["estimated_runtime"] is False


def test_failed_hydration_does_not_invent_completion_from_season_count():
    rec = {"episodes": {"s01e001": {"watched": True, "provenance": "explicit"}}}
    seasons = [{
        "season_number": 1,
        "episode_count": 1,
        "metadata_provenance": "tmdb_season_unavailable",
    }]
    result = completion_metadata(rec, seasons, runtime=45)
    assert result["eligible_episode_count"] is None
    assert result["completed"] is None
    assert result["eligible_count_provenance"] == "unknown"


def test_partial_air_dates_make_completion_unknown():
    rec = {"episodes": {"s01e001": {"watched": True, "provenance": "explicit"}}}
    seasons = [{
        "season_number": 1,
        "episode_count": 2,
        "metadata_provenance": "tmdb_season",
        "episodes": [
            {"episode_key": "s01e001", "air_date": "2020-01-01", "runtime": 45},
            {"episode_key": "s01e002", "air_date": None, "runtime": 45},
        ],
    }]
    result = completion_metadata(rec, seasons, runtime=45)
    assert result["eligible_episode_count"] is None
    assert result["completed"] is None
    assert result["eligible_count_provenance"] == "unknown"


def test_watched_future_episode_cannot_replace_missing_released_episode():
    rec = {"episodes": {
        "s01e001": {"watched": True, "provenance": "explicit"},
        "s01e003": {"watched": True, "provenance": "explicit"},
    }}
    seasons = [{
        "season_number": 1,
        "episode_count": 3,
        "metadata_provenance": "tmdb_season",
        "episodes": [
            {"episode_key": "s01e001", "air_date": "2020-01-01"},
            {"episode_key": "s01e002", "air_date": "2020-01-08"},
            {"episode_key": "s01e003", "air_date": "2999-01-01"},
        ],
    }]
    result = completion_metadata(rec, seasons)
    assert result["eligible_episode_count"] == 2
    assert result["watched_released_episode_count"] == 1
    assert result["completed"] is False


def test_bulk_inference_recorded_before_air_date_does_not_precomplete_release():
    rec = {"episodes": {
        "s01e001": {
            "watched": True,
            "provenance": "bulk_inferred",
            "updated_at": "2019-12-01T12:00:00+00:00",
        },
    }}
    seasons = [{
        "season_number": 1,
        "episode_count": 1,
        "metadata_provenance": "tmdb_season",
        "episodes": [{"episode_key": "s01e001", "air_date": "2020-01-01"}],
    }]
    result = completion_metadata(rec, seasons)
    assert result["watched_released_episode_count"] == 0
    assert result["completed"] is False