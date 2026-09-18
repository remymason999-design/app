"""Repeatable WatchSmart+ persistence, privacy, affiliate and scoring contracts."""
import asyncio
from types import SimpleNamespace

from fastapi import Response
from pymongo.errors import DuplicateKeyError
from starlette.requests import Request

import monetization as contracts
from routers import affiliate, auth, monetization


def run(coro):
    return asyncio.run(coro)


async def unlocked(*_args, **_kwargs):
    return True


async def released(*_args, **_kwargs):
    return None


async def fenced(_user_id, _owner, operation, **_kwargs):
    return await operation()


class InterestCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query, projection=None):
        row = self.rows.get(query["user_id"])
        return dict(row) if row else None

    async def find_one_and_update(self, query, update, **_kwargs):
        uid = query["user_id"]
        row = self.rows.get(uid)
        required = query.get("interested")
        if required is True and (not row or row.get("interested") is not True):
            return None
        if isinstance(required, dict) and required.get("$ne") is True and row and row.get("interested") is True:
            return None
        row = dict(row or {})
        if not row:
            row.update(update.get("$setOnInsert", {}))
        row.update(update.get("$set", {}))
        self.rows[uid] = row
        return dict(row)


class ExistingUsers:
    async def find_one(self, query, projection=None):
        return {"_id": query["user_id"]}


class EventCollection:
    def __init__(self):
        self.rows = {}

    async def insert_one(self, row):
        if row["event_id"] in self.rows:
            raise DuplicateKeyError("duplicate")
        self.rows[row["event_id"]] = dict(row)


def install_interest_db(monkeypatch):
    interests = InterestCollection()
    events = EventCollection()
    monkeypatch.setattr(
        monetization,
        "db",
        SimpleNamespace(users=ExistingUsers(), plus_interest=interests, plus_events=events),
    )
    monkeypatch.setattr(monetization, "run_under_user_deletion_fence", fenced)
    return interests, events


def test_legacy_accounts_default_to_free_without_entitlements():
    result = contracts.resolve_account_entitlements({
        "subscription_tier": "forged",
        "subscription_status": "active",
        "subscription_product_id": {"unsafe": True},
    })
    assert result["subscription_tier"] == "free"
    assert result["subscription_status"] == "none"
    assert result["subscription_product_id"] is None
    assert result["entitlements"] == []
    assert not any(result["feature_access"].values())


def test_interest_ignores_spoofed_identity_and_tier_and_is_idempotent(monkeypatch):
    interests, events = install_interest_db(monkeypatch)
    payload = monetization.PlusInterestIn.model_validate({
        "source_screen": "profile",
        "user_id": "attacker-choice",
        "subscription_tier": "plus",
    })
    user = {"user_id": "real-user", "created_at": "2026-09-01T00:00:00Z"}
    first = run(monetization.add_plus_interest(payload, user))
    second = run(monetization.add_plus_interest(payload, user))
    assert first == {
        "interested": True,
        "changed": True,
        "message": "You're on the list. We'll let you know when WatchSmart+ is ready.",
    }
    assert second["changed"] is False
    assert set(interests.rows) == {"real-user"}
    assert len(events.rows) == 1


def test_add_remove_are_isolated_per_authenticated_user(monkeypatch):
    interests, _events = install_interest_db(monkeypatch)
    payload = monetization.PlusInterestIn(source_screen="plus_preview")
    run(monetization.add_plus_interest(payload, {"user_id": "one"}))
    run(monetization.add_plus_interest(payload, {"user_id": "two"}))
    removed = run(monetization.remove_plus_interest({"user_id": "one"}))
    removed_again = run(monetization.remove_plus_interest({"user_id": "one"}))
    assert removed["changed"] is True
    assert removed_again["changed"] is False
    assert interests.rows["one"]["interested"] is False
    assert interests.rows["two"]["interested"] is True


def test_event_ids_deduplicate_and_event_payload_is_privacy_minimised(monkeypatch):
    events = EventCollection()
    monkeypatch.setattr(monetization, "db", SimpleNamespace(plus_events=events))
    user = {
        "user_id": "one",
        "email": "private@example.test",
        "name": "Private Person",
        "created_at": "2026-09-01T00:00:00Z",
        "onboarding_completed": True,
    }
    event_id = "event_identifier_1234"
    assert run(monetization.record_plus_event(
        user=user, event_name="plus_preview_viewed", event_id=event_id,
        source_screen="profile", platform="ios",
    )) is True
    assert run(monetization.record_plus_event(
        user=user, event_name="plus_preview_viewed", event_id=event_id,
    )) is False
    row = events.rows[event_id]
    assert "email" not in row and "name" not in row
    assert row["cohort"] == {"signup_period": "2026-09", "onboarding": "completed"}


class NeverInsert:
    async def insert_one(self, _row):
        raise AssertionError("disabled affiliate tracking must not write")


def test_disabled_affiliate_tracking_preserves_exact_destination(monkeypatch):
    destination = "https://provider.example/watch?existing=1&internal_user_id=provider-owned"
    monkeypatch.setitem(affiliate.MONETIZATION_FLAGS, "affiliate_tracking_enabled", False)
    monkeypatch.setattr(affiliate, "STREAMING_SERVICES", [{
        "id": "provider", "name": "Provider", "affiliate_url": destination,
    }])
    monkeypatch.setattr(affiliate, "find_movie", lambda _movie_id: {"id": "movie-1", "title": "Film"})
    monkeypatch.setattr(affiliate, "db", SimpleNamespace(affiliate_clicks=NeverInsert()))
    payload = affiliate.AffiliateClickIn(
        movie_id="movie-1", service_id="provider", campaign_id="internal-campaign",
        partner_id="internal-partner",
    )
    result = run(affiliate.affiliate_click(payload, None, {"user_id": "internal-user"}))
    assert result == {"url": destination}


def test_sponsorship_metadata_cannot_change_organic_score_or_order():
    organic = [
        {"id": "a", "score": 9.2},
        {"id": "b", "score": 8.7},
        {"id": "c", "score": 7.1},
    ]
    decorated = [
        {**row, "sponsorship": contracts.sponsorship_metadata({
            "is_sponsored": row["id"] == "c",
            "sponsor_name": "Example",
            "campaign_id": "campaign",
            "score": 999,
        })}
        for row in organic
    ]
    assert [row["id"] for row in sorted(decorated, key=lambda row: row["score"], reverse=True)] == ["a", "b", "c"]
    assert [row["score"] for row in decorated] == [9.2, 8.7, 7.1]
    assert all("score" not in row["sponsorship"] for row in decorated)


class DeletionCollection:
    def __init__(self):
        self.deleted = []

    async def delete_many(self, query):
        self.deleted.append(query)

    async def update_many(self, *_args, **_kwargs):
        return None

    async def delete_one(self, query):
        self.deleted.append(query)


def test_account_deletion_cleans_watchsmart_plus_records(monkeypatch):
    names = [
        "user_sessions", "user_actions", "affiliate_clicks", "notifications",
        "push_devices", "notification_outbox", "push_receipts", "user_reviews",
        "friends", "share_requests", "password_resets", "plus_interest",
        "plus_events", "plus_launch_deliveries", "users",
    ]
    collections = {name: DeletionCollection() for name in names}
    monkeypatch.setattr(auth, "db", SimpleNamespace(**collections))
    monkeypatch.setattr(auth, "run_under_user_deletion_fence", fenced)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer token")]})
    result = run(auth.delete_account(Response(), request, {"user_id": "one"}))
    assert result == {"ok": True}
    for name in ("plus_interest", "plus_events", "plus_launch_deliveries"):
        assert collections[name].deleted == [{"user_id": "one"}]