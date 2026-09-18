"""Focused tests for approval-gated WatchSmart+ launch delivery."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

import plus_launch
import push_notifications
from routers import monetization


class _OneCursor:
    def __init__(self, docs):
        self.docs = docs

    def limit(self, _limit):
        return self

    def sort(self, _field, _direction):
        return self

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Interest:
    def __init__(self, current):
        self.current = current

    def find(self, query, projection=None):
        return _OneCursor([{"user_id": "user-1"}] if self.current else [])

    async def find_one(self, query, projection=None):
        return {"_id": "interest"} if self.current else None


class _State:
    def __init__(self, status):
        self.status = status

    async def find_one(self, query, projection=None):
        return {"campaign_id": plus_launch.CAMPAIGN_ID, "status": self.status}


class _Outbox:
    def __init__(self):
        self.update = None

    async def update_one(self, query, update):
        self.update = (query, update)

    async def find_one(self, query, projection=None):
        return {"_id": "outbox"}


def test_user_deletion_fence_verifies_after_lock_and_releases_on_failure(monkeypatch):
    calls = []

    class _Users:
        async def find_one(self, query, projection=None):
            calls.append("verify")
            return {"_id": query["user_id"]}

    async def acquire(*args, **kwargs):
        calls.append("acquire")
        return True

    async def release(*args, **kwargs):
        calls.append("release")

    async def operation():
        calls.append("operate")
        raise ValueError("write failed")

    monkeypatch.setattr(push_notifications, "db", SimpleNamespace(users=_Users()))
    monkeypatch.setattr(push_notifications, "acquire_push_delivery_lock", acquire)
    monkeypatch.setattr(push_notifications, "release_push_delivery_lock", release)

    with pytest.raises(ValueError, match="write failed"):
        asyncio.run(push_notifications.run_under_user_deletion_fence(
            "user-1", "owner-1", operation
        ))
    assert calls == ["acquire", "verify", "operate", "release"]


def test_user_deletion_fence_releases_without_running_after_deletion(monkeypatch):
    calls = []

    class _Users:
        async def find_one(self, query, projection=None):
            calls.append("verify")
            return None

    async def acquire(*args, **kwargs):
        calls.append("acquire")
        return True

    async def release(*args, **kwargs):
        calls.append("release")

    async def operation():
        calls.append("operate")

    monkeypatch.setattr(push_notifications, "db", SimpleNamespace(users=_Users()))
    monkeypatch.setattr(push_notifications, "acquire_push_delivery_lock", acquire)
    monkeypatch.setattr(push_notifications, "release_push_delivery_lock", release)

    with pytest.raises(push_notifications.UserNoLongerExists):
        asyncio.run(push_notifications.run_under_user_deletion_fence(
            "user-1", "owner-1", operation
        ))
    assert calls == ["acquire", "verify", "release"]


def test_dispatch_is_disabled_until_launch_approval(monkeypatch):
    monkeypatch.setattr(
        plus_launch,
        "db",
        SimpleNamespace(plus_launch_state=_State("draft")),
    )
    with pytest.raises(PermissionError):
        asyncio.run(plus_launch.dispatch_channel("email"))


def test_push_worker_cancels_after_interest_is_removed(monkeypatch):
    outbox = _Outbox()
    monkeypatch.setattr(
        push_notifications,
        "db",
        SimpleNamespace(
            plus_interest=_Interest(False),
            notification_outbox=outbox,
        ),
    )
    async def acquire(*args, **kwargs):
        return True

    async def release(*args, **kwargs):
        return None

    monkeypatch.setattr(push_notifications, "acquire_push_delivery_lock", acquire)
    monkeypatch.setattr(push_notifications, "release_push_delivery_lock", release)
    event = {
        "event_id": "push-1",
        "user_id": "user-1",
        "claim_id": "claim-1",
        "consent_kind": "plus_interest",
        "title": "WatchSmart+ is ready",
        "body": "Open WatchSmart.",
        "data": {},
    }
    asyncio.run(push_notifications._deliver_to_device(None, event, "ExpoPushToken[token]"))
    query, update = outbox.update
    assert query["claim_id"] == "claim-1"
    assert update["$set"]["status"] == "cancelled"
    assert update["$set"]["delivery"] == "interest_removed"


def test_add_interest_rejects_when_account_already_deleted(monkeypatch):
    """Mutation-after-deletion ordering: a request that acquires the shared
    per-user lock *after* account deletion released it must not resurrect a
    plus_interest row for a user who no longer exists."""

    class _Users:
        async def find_one(self, query, projection=None):
            return None  # deletion already removed the user document

    monkeypatch.setattr(
        monetization,
        "db",
        SimpleNamespace(users=_Users()),
    )

    async def deleted_fence(*args, **kwargs):
        raise monetization.UserNoLongerExists("user-1")

    monkeypatch.setattr(monetization, "run_under_user_deletion_fence", deleted_fence)

    payload = monetization.PlusInterestIn(source_screen="plus_preview")
    user = {"user_id": "user-1", "created_at": None}
    with pytest.raises(Exception) as exc_info:
        asyncio.run(monetization.add_plus_interest(payload, user))
    assert getattr(exc_info.value, "status_code", None) == 401


def test_dispatch_skips_delivery_claim_when_deletion_wins_the_lock(monkeypatch):
    """Deletion-first ordering: if account deletion completes (and removes
    plus_interest) before dispatch acquires the per-user lock, dispatch must
    not create a new plus_launch_deliveries row for that user."""

    class _NeverCalled:
        async def insert_one(self, doc):
            raise AssertionError("must not create a delivery row post-deletion")

        async def find_one_and_update(self, *args, **kwargs):
            raise AssertionError("must not claim a delivery row post-deletion")

    class _GoneInterest:
        def find(self, query, projection=None):
            return _OneCursor([{"user_id": "user-1"}])

        async def find_one(self, query, projection=None):
            return None  # deletion already removed the interest row

    monkeypatch.setattr(
        plus_launch,
        "db",
        SimpleNamespace(
            plus_launch_state=_State("approved"),
            plus_interest=_GoneInterest(),
            plus_launch_deliveries=_NeverCalled(),
        ),
    )

    async def acquire(*args, **kwargs):
        return True

    async def release(*args, **kwargs):
        return None

    async def fenced(_user_id, _owner, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(plus_launch, "acquire_push_delivery_lock", acquire)
    monkeypatch.setattr(plus_launch, "release_push_delivery_lock", release)
    monkeypatch.setattr(plus_launch, "run_under_user_deletion_fence", fenced)

    summary = asyncio.run(plus_launch.dispatch_channel("push"))
    assert summary["eligible"] == 1
    assert summary["sent"] == 0
    assert summary["cancelled"] == 0


def test_ambiguous_email_is_not_resent_after_idempotency_window_expires(monkeypatch):
    """An email delivery stuck in 'retry' (ambiguous provider_error) must stop
    being retried once it is past the safe margin under Resend's 24-hour
    idempotency-key retention, since a retry past that point would no longer
    be deduplicated and could send a duplicate launch email."""
    import plus_launch as pl

    stale_created_at = pl._now() - (pl.EMAIL_IDEMPOTENCY_SAFE_RETRY_WINDOW + timedelta(hours=1))

    class _StaleDeliveries:
        def __init__(self):
            self.finished = None

        async def insert_one(self, doc):
            from pymongo.errors import DuplicateKeyError

            raise DuplicateKeyError("delivery already exists")

        async def find_one_and_update(self, query, update, **kwargs):
            return {
                "delivery_key": f"{pl.CAMPAIGN_ID}:email:user-1",
                "campaign_id": pl.CAMPAIGN_ID,
                "user_id": "user-1",
                "channel": "email",
                "status": "processing",
                "claim_id": "claim-stale",
                "created_at": stale_created_at,
            }

        async def update_one(self, query, update):
            self.finished = (query, update)

    class _Interested:
        def find(self, query, projection=None):
            return _OneCursor([{"user_id": "user-1"}])

        async def find_one(self, query, projection=None):
            return {"_id": "interest"}

    class _NeverCalledEmail:
        async def find_one(self, query, projection=None):
            raise AssertionError("must not look up the email address")

    deliveries = _StaleDeliveries()
    monkeypatch.setattr(
        plus_launch,
        "db",
        SimpleNamespace(
            plus_launch_state=_State("approved"),
            plus_interest=_Interested(),
            plus_launch_deliveries=deliveries,
            users=_NeverCalledEmail(),
        ),
    )

    async def acquire(*args, **kwargs):
        return True

    async def release(*args, **kwargs):
        return None

    async def _send_email_must_not_be_called(*args, **kwargs):
        raise AssertionError("must not call the email provider past the safe retry window")

    async def fenced(_user_id, _owner, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(plus_launch, "acquire_push_delivery_lock", acquire)
    monkeypatch.setattr(plus_launch, "release_push_delivery_lock", release)
    monkeypatch.setattr(plus_launch, "run_under_user_deletion_fence", fenced)
    monkeypatch.setattr(plus_launch, "send_email", _send_email_must_not_be_called)

    summary = asyncio.run(plus_launch.dispatch_channel("email"))
    assert summary["failed"] == 1
    assert summary["sent"] == 0
    query, update = deliveries.finished
    assert update["$set"]["status"] == "failed"
    assert update["$set"]["outcome"] == "idempotency_window_expired"


def test_required_push_queue_failure_is_not_silently_accepted(monkeypatch):
    class _Notifications:
        async def insert_one(self, doc):
            return None

    class _FailingOutbox:
        async def insert_one(self, doc):
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr(
        push_notifications,
        "db",
        SimpleNamespace(
            notifications=_Notifications(),
            notification_outbox=_FailingOutbox(),
        ),
    )
    with pytest.raises(RuntimeError, match="queue unavailable"):
        asyncio.run(push_notifications.create_user_notification(
            "user-1",
            title="WatchSmart+ is ready",
            body="Open WatchSmart.",
            kind="plus_launch",
            require_push_queue=True,
        ))