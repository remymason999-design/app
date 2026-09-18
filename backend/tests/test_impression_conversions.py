from routers.admin import _build_impression_conversion_report


def test_impression_conversion_report_attributes_first_valid_linked_action():
    impressions = [{
        "user_id": "u1",
        "impression_id": "feed-1",
        "at": "2026-09-01T10:00:00+00:00",
        "items": [
            {"id": 1, "reason_code": "taste", "slot": "core", "served_at": "2026-09-01T10:00:00+00:00"},
            {"id": 2, "reason_code": "explore", "slot": "wildcard", "served_at": "2026-09-01T10:00:00+00:00"},
        ],
    }]
    actions = [
        # Before serving, wrong user, and wrong movie are all ignored.
        {"user_id": "u1", "impression_id": "feed-1", "movie_id": 1, "action": "skip", "created_at": "2026-09-01T09:59:00+00:00"},
        {"user_id": "u2", "impression_id": "feed-1", "movie_id": 1, "action": "save", "created_at": "2026-09-01T10:01:00+00:00"},
        {"user_id": "u1", "impression_id": "feed-1", "movie_id": 99, "action": "save", "created_at": "2026-09-01T10:01:00+00:00"},
        # First valid terminal outcome wins.
        {"user_id": "u1", "impression_id": "feed-1", "movie_id": 1, "action": "save", "created_at": "2026-09-01T10:02:00+00:00"},
        {"user_id": "u1", "impression_id": "feed-1", "movie_id": 1, "action": "skip", "created_at": "2026-09-01T10:03:00+00:00"},
        {"user_id": "u1", "impression_id": "feed-1", "movie_id": 2, "action": "skip", "created_at": "2026-09-01T10:04:00+00:00"},
    ]

    report = _build_impression_conversion_report(impressions, actions, {1: "A", 2: "D"})

    assert report["summary"] == {
        "impressions": 2,
        "responded": 2,
        "response_rate_pct": 100.0,
    }
    by_reason = {row["value"]: row for row in report["by_reason_code"]}
    assert by_reason["taste"]["saves"] == 1
    assert by_reason["taste"]["save_rate_pct"] == 100.0
    assert by_reason["explore"]["skips"] == 1
    assert by_reason["explore"]["skip_rate_pct"] == 100.0
    assert {row["value"] for row in report["by_quality_tier"]} == {"A", "D"}


def test_impression_conversion_report_handles_empty_data():
    report = _build_impression_conversion_report([], [], {})
    assert report["summary"]["impressions"] == 0
    assert report["summary"]["response_rate_pct"] is None
    assert report["by_slot"] == []