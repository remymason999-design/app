"""Focused tests for authenticated push registration and durable enqueueing."""
import asyncio
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from push_notifications import create_user_notification
from routers import notifications
import push_notifications


class _InsertCollection:
    def __init__(self, error=None):
        self.docs = []
        self.error = error

    async def insert_one(self, doc):
        if self.error:
            raise self.error
        self.docs.append(dict(doc))

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


class _UniqueOutbox(_InsertCollection):
    async def insert_one(self, doc):
        if any(item.get("dedupe_key") == doc.get("dedupe_key") for item in self.docs):
            raise DuplicateKeyError("duplicate dedupe_key")
        await super().insert_one(doc)


class _DeviceCollection:
    def __init__(self):
        self.updated = None
        self.deleted = None

    async def update_one(self, query, update, upsert=False):
        self.updated = (query, update, upsert)

    async def delete_many(self, query):
        return SimpleNamespace(deleted_count=0)

    async def delete_one(self, query):
        self.deleted = query


def test_expo_token_validation():
    assert notifications._valid_expo_token("ExponentPushToken[abcdefghijklmnopqrst]")
    assert notifications._valid_expo_token("ExpoPushToken[abcdefghijklmnopqrst]")
    assert not notifications._valid_expo_token("plain-device-token")


def test_registration_is_bound_to_authenticated_user(monkeypatch):
    devices = _DeviceCollection()
    monkeypatch.setattr(
        notifications,
        "db",
        SimpleNamespace(push_devices=devices),
    )
    payload = notifications.PushDeviceIn(
        expo_token="ExpoPushToken[abcdefghijklmnopqrst]",
        installation_id="installation_abcdefghijklmnopqrst",
        unregister_secret="secret_abcdefghijklmnopqrstuvwxyz_123456",
        platform="ios",
        app_version="1.0.0",
    )
    result = asyncio.run(
        notifications.register_push_device(payload, {"user_id": "authenticated-user"})
    )
    assert result == {"ok": True}
    query, update, upsert = devices.updated
    assert query == {"installation_id": payload.installation_id}
    assert update["$set"]["user_id"] == "authenticated-user"
    assert update["$set"]["unregister_secret_hash"] != payload.unregister_secret
    assert update["$set"]["expires_at"] > update["$set"]["updated_at"]
    assert upsert is True


def test_push_queue_failure_does_not_undo_in_app_notification(monkeypatch):
    in_app = _InsertCollection()
    outbox = _InsertCollection(error=RuntimeError("temporary queue failure"))
    monkeypatch.setattr(
        push_notifications,
        "db",
        SimpleNamespace(notifications=in_app, notification_outbox=outbox),
    )
    notification_id = asyncio.run(
        create_user_notification(
            "user-1",
            title="New watchlist request",
            body="A named user requested access.",
            kind="share_request",
            push_body="You have a new watchlist request.",
            route="/(tabs)/friends",
            dedupe_key="share_request:req-1",
        )
    )
    assert notification_id.startswith("notif_")
    assert len(in_app.docs) == 1
    assert in_app.docs[0]["body"] == "A named user requested access."


def test_push_outbox_contains_only_generic_route_payload(monkeypatch):
    in_app = _InsertCollection()
    outbox = _InsertCollection()
    monkeypatch.setattr(
        push_notifications,
        "db",
        SimpleNamespace(notifications=in_app, notification_outbox=outbox),
    )
    asyncio.run(
        create_user_notification(
            "user-1",
            title="New watchlist request",
            body="Private Name wants to compare watchlists.",
            kind="share_request",
            push_body="You have a new watchlist request.",
            route="/(tabs)/friends",
        )
    )
    event = outbox.docs[0]
    assert "Private Name" not in event["body"]
    assert event["data"]["route"] == "/(tabs)/friends"
    assert set(event["data"]) == {"notification_id", "kind", "route"}


def test_outbox_deduplicates_repeated_event(monkeypatch):
    in_app = _InsertCollection()
    outbox = _UniqueOutbox()
    monkeypatch.setattr(
        push_notifications,
        "db",
        SimpleNamespace(notifications=in_app, notification_outbox=outbox),
    )

    async def enqueue_twice():
        for _ in range(2):
            await create_user_notification(
                "user-1",
                title="Accepted",
                body="A request was accepted.",
                kind="share_accepted",
                push_body="Your watchlist request was accepted.",
                route="/(tabs)/friends",
                dedupe_key="share_accepted:req-1",
            )

    asyncio.run(enqueue_twice())
    assert len(outbox.docs) == 1


def test_retry_update_is_fenced_to_the_worker_claim(monkeypatch):
    outbox = _DeviceCollection()
    monkeypatch.setattr(
        push_notifications,
        "db",
        SimpleNamespace(notification_outbox=outbox),
    )
    event = {"event_id": "event-1", "claim_id": "claim-1", "attempts": 1}
    asyncio.run(push_notifications._retry_or_fail(event, "temporary failure"))
    query, update, _ = outbox.updated
    assert query == {
        "event_id": "event-1",
        "status": "processing",
        "claim_id": "claim-1",
    }
    assert update["$set"]["status"] == "retry"