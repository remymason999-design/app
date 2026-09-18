"""Durable Expo push delivery for WatchSmart notifications."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import db, logger

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_user_notification(
    user_id: str,
    *,
    title: str,
    body: str,
    kind: str,
    push_title: str | None = None,
    push_body: str | None = None,
    route: str = "/profile",
    dedupe_key: str | None = None,
    consent_kind: str | None = None,
    campaign_id: str | None = None,
    require_push_queue: bool = False,
) -> str:
    """Persist the in-app item first, then independently queue a generic push."""
    notification_id = f"notif_{uuid.uuid4().hex}"
    now = _now()
    notification_doc = {
        "notification_id": notification_id,
        "user_id": user_id,
        "title": title,
        "body": body,
        "kind": kind,
        "read": False,
        "created_at": now.isoformat(),
    }
    if dedupe_key:
        notification_doc["dedupe_key"] = dedupe_key
    try:
        await db.notifications.insert_one(notification_doc)
    except DuplicateKeyError:
        existing = await db.notifications.find_one(
            {"dedupe_key": dedupe_key},
            {"_id": 0, "notification_id": 1},
        )
        if not existing or not existing.get("notification_id"):
            raise
        notification_id = existing["notification_id"]
    event = {
        "event_id": f"push_{uuid.uuid4().hex}",
        "user_id": user_id,
        "notification_id": notification_id,
        "title": push_title or title,
        "body": push_body or body,
        "data": {
            "notification_id": notification_id,
            "kind": kind,
            "route": route,
        },
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": now,
        "created_at": now,
    }
    if dedupe_key:
        event["dedupe_key"] = dedupe_key
    if consent_kind:
        event["consent_kind"] = consent_kind
    if campaign_id:
        event["campaign_id"] = campaign_id
    try:
        await db.notification_outbox.insert_one(event)
    except DuplicateKeyError:
        pass
    except Exception as exc:  # noqa: BLE001
        # Push is supplementary: never undo or fail an in-app notification.
        logger.warning("Could not queue push notification: %s", exc)
        if require_push_queue:
            raise
    return notification_id


def _expo_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
    }
    token = os.environ.get("EXPO_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _disable_device(expo_token: str, reason: str) -> None:
    await db.push_devices.update_one(
        {"expo_token": expo_token},
        {"$set": {"active": False, "disabled_reason": reason, "updated_at": _now()}},
    )


async def acquire_push_delivery_lock(
    user_id: str,
    owner: str,
    *,
    wait_seconds: float = 0,
    lease_seconds: int = 30,
) -> bool:
    """Acquire a short distributed per-user fence before calling Expo."""
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        now = _now()
        try:
            lock = await db.push_delivery_locks.find_one_and_update(
                {
                    "user_id": user_id,
                    "$or": [
                        {"owner": owner},
                        {"expires_at": {"$lte": now}},
                    ],
                },
                {
                    "$set": {
                        "owner": owner,
                        "expires_at": now + timedelta(seconds=lease_seconds),
                    },
                    "$setOnInsert": {"user_id": user_id},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            if lock and lock.get("owner") == owner:
                return True
        except DuplicateKeyError:
            pass
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.2)


async def release_push_delivery_lock(user_id: str, owner: str) -> None:
    await db.push_delivery_locks.delete_one({"user_id": user_id, "owner": owner})


class UserDeletionFenceBusy(RuntimeError):
    """The per-user deletion fence could not be acquired in time."""


class UserNoLongerExists(RuntimeError):
    """The user was deleted before the deletion fence was acquired."""


_DeletionFenceResult = TypeVar("_DeletionFenceResult")


async def run_under_user_deletion_fence(
    user_id: str,
    owner: str,
    operation: Callable[[], Awaitable[_DeletionFenceResult]],
    *,
    wait_seconds: float = 0,
    lease_seconds: int = 30,
    suppress_release_errors: bool = False,
) -> _DeletionFenceResult:
    """Run a user-data operation only while the user is live and fenced.

    Any new feature that creates or changes per-user data removed by account
    deletion must use this helper. It acquires the shared fence, re-verifies
    user existence after acquisition, and always releases the fence.
    """
    if not await acquire_push_delivery_lock(
        user_id,
        owner,
        wait_seconds=wait_seconds,
        lease_seconds=lease_seconds,
    ):
        raise UserDeletionFenceBusy(user_id)
    try:
        if not await db.users.find_one({"user_id": user_id}, {"_id": 1}):
            raise UserNoLongerExists(user_id)
        return await operation()
    finally:
        try:
            await release_push_delivery_lock(user_id, owner)
        except Exception as exc:
            if not suppress_release_errors:
                raise
            logger.warning(
                "User operation completed; deletion-fence cleanup deferred to TTL: %s",
                exc,
            )


async def _retry_or_fail(event: dict, reason: str) -> None:
    attempts = int(event.get("attempts") or 1)
    claim_query = {
        "event_id": event["event_id"],
        "status": "processing",
        "claim_id": event["claim_id"],
    }
    if attempts >= 5:
        await db.notification_outbox.update_one(
            claim_query,
            {
                "$set": {
                    "status": "failed",
                    "last_error": reason[:300],
                    "updated_at": _now(),
                },
                "$unset": {"claim_id": ""},
            },
        )
        return
    delay = min(900, 15 * (2 ** max(0, attempts - 1)))
    await db.notification_outbox.update_one(
        claim_query,
        {
            "$set": {
                "status": "retry",
                "last_error": reason[:300],
                "next_attempt_at": _now() + timedelta(seconds=delay),
                "updated_at": _now(),
            },
            "$unset": {"claim_id": ""},
        },
    )


async def _deliver_to_device(
    client: httpx.AsyncClient,
    event: dict,
    token: str,
) -> bool:
    claim_query = {
        "event_id": event["event_id"],
        "status": "processing",
        "claim_id": event["claim_id"],
    }
    if not await db.notification_outbox.find_one(claim_query, {"_id": 1}):
        return False
    message = {
        "to": token,
        "sound": "default",
        "title": event["title"],
        "body": event["body"],
        "data": event["data"],
        "priority": "high",
    }
    lock_owner = f"delivery:{event['event_id']}:{event['claim_id']}:{uuid.uuid4().hex}"
    campaign_lock_key = (
        f"campaign:{event['campaign_id']}" if event.get("campaign_id") else None
    )
    if campaign_lock_key and not await acquire_push_delivery_lock(
        campaign_lock_key, lock_owner, wait_seconds=1
    ):
        raise RuntimeError("Push campaign delivery is temporarily locked")
    user_locked = False
    try:
        if not await acquire_push_delivery_lock(
            event["user_id"], lock_owner, wait_seconds=1
        ):
            raise RuntimeError("Push delivery is temporarily locked")
        user_locked = True
        if event.get("campaign_id"):
            state = await db.plus_launch_state.find_one(
                {
                    "campaign_id": event["campaign_id"],
                    "status": "approved",
                },
                {"_id": 1},
            )
            if not state:
                await db.notification_outbox.update_one(
                    claim_query,
                    {
                        "$set": {
                            "status": "cancelled",
                            "delivery": "approval_revoked",
                            "updated_at": _now(),
                        },
                        "$unset": {"claim_id": ""},
                    },
                )
                return False
        if event.get("consent_kind") == "plus_interest":
            interested = await db.plus_interest.find_one(
                {"user_id": event["user_id"], "interested": True},
                {"_id": 1},
            )
            if not interested:
                await db.notification_outbox.update_one(
                    claim_query,
                    {
                        "$set": {
                            "status": "cancelled",
                            "delivery": "interest_removed",
                            "updated_at": _now(),
                        },
                        "$unset": {"claim_id": ""},
                    },
                )
                return False
        if not await db.notification_outbox.find_one(claim_query, {"_id": 1}):
            return False
        response = await client.post(
            EXPO_PUSH_URL,
            headers=_expo_headers(),
            json=message,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise RuntimeError(f"Expo push service returned {response.status_code}")
        if response.status_code >= 400:
            raise RuntimeError(f"Expo rejected request ({response.status_code})")
        ticket: Any = response.json().get("data")
        if not isinstance(ticket, dict) or not ticket.get("status"):
            raise RuntimeError("Expo returned a malformed push ticket")
        error = ticket.get("details", {}).get("error")
        if ticket.get("status") == "ok" and ticket.get("id"):
            await db.push_receipts.update_one(
                {"ticket_id": ticket["id"]},
                {
                    "$setOnInsert": {
                        "ticket_id": ticket["id"],
                        "expo_token": token,
                        "user_id": event["user_id"],
                        "event_id": event["event_id"],
                        "status": "pending",
                        "check_after": _now() + timedelta(minutes=15),
                        "created_at": _now(),
                    }
                },
                upsert=True,
            )
        elif error == "DeviceNotRegistered":
            await _disable_device(token, "DeviceNotRegistered")
        elif error in {
            "MessageRateExceeded",
            "InvalidCredentials",
            "MismatchSenderId",
        }:
            raise RuntimeError(f"Expo ticket error: {error}")
        elif error == "MessageTooBig":
            pass
        elif ticket.get("status") == "error":
            raise RuntimeError(f"Expo ticket error: {error or 'unknown'}")
        else:
            raise RuntimeError("Expo returned an incomplete push ticket")
        update: dict[str, Any] = {
            "$addToSet": {"delivered_tokens": token},
            "$set": {"updated_at": _now()},
        }
        if error in {"DeviceNotRegistered", "MessageTooBig"}:
            update["$addToSet"]["delivery_failures"] = {
                "expo_token": token,
                "error": error,
            }
        result = await db.notification_outbox.update_one(claim_query, update)
        return result.modified_count == 1
    finally:
        if user_locked:
            await release_push_delivery_lock(event["user_id"], lock_owner)
        if campaign_lock_key:
            await release_push_delivery_lock(campaign_lock_key, lock_owner)


async def _deliver_event(client: httpx.AsyncClient, event: dict) -> None:
    devices = []
    async for device in db.push_devices.find(
        {
            "user_id": event["user_id"],
            "active": True,
            "expires_at": {"$gt": _now()},
        },
        {"_id": 0, "expo_token": 1},
    ).limit(20):
        devices.append(device["expo_token"])
    if not devices:
        await db.notification_outbox.update_one(
            {
                "event_id": event["event_id"],
                "status": "processing",
                "claim_id": event["claim_id"],
            },
            {
                "$set": {
                    "status": "sent",
                    "delivery": "no_active_devices",
                    "updated_at": _now(),
                },
                "$unset": {"claim_id": ""},
            },
        )
        return

    delivered = set(event.get("delivered_tokens") or [])
    for token in devices:
        if token in delivered:
            continue
        if not await _deliver_to_device(client, event, token):
            return
        delivered.add(token)
    final_status = "partial" if event.get("delivery_failures") else "sent"
    if await db.notification_outbox.find_one(
        {
            "event_id": event["event_id"],
            "delivery_failures.0": {"$exists": True},
        },
        {"_id": 1},
    ):
        final_status = "partial"
    await db.notification_outbox.update_one(
        {
            "event_id": event["event_id"],
            "status": "processing",
            "claim_id": event["claim_id"],
        },
        {
            "$set": {"status": final_status, "updated_at": _now()},
            "$unset": {"claim_id": ""},
        },
    )


async def _check_receipts(client: httpx.AsyncClient) -> None:
    receipts = []
    async for receipt in db.push_receipts.find(
        {"status": "pending", "check_after": {"$lte": _now()}},
        {"_id": 0},
    ).limit(100):
        receipts.append(receipt)
    if not receipts:
        return
    response = await client.post(
        EXPO_RECEIPTS_URL,
        headers=_expo_headers(),
        json={"ids": [receipt["ticket_id"] for receipt in receipts]},
    )
    if response.status_code >= 400:
        await db.push_receipts.update_many(
            {"ticket_id": {"$in": [receipt["ticket_id"] for receipt in receipts]}},
            {"$set": {"check_after": _now() + timedelta(minutes=5)}},
        )
        return
    results = response.json().get("data", {})
    by_id = {receipt["ticket_id"]: receipt for receipt in receipts}
    for ticket_id, result in results.items():
        receipt = by_id.get(ticket_id)
        if not receipt:
            continue
        error = result.get("details", {}).get("error")
        retryable = error not in {"DeviceNotRegistered", "MessageTooBig"}
        if error == "DeviceNotRegistered":
            await _disable_device(receipt["expo_token"], error)
        if retryable and result.get("status") != "ok":
            requeued = await db.notification_outbox.update_one(
                {
                    "event_id": receipt["event_id"],
                    "status": {"$in": ["sent", "partial", "retry"]},
                    "attempts": {"$lt": 5},
                },
                {
                    "$set": {
                        "status": "retry",
                        "next_attempt_at": _now() + timedelta(minutes=1),
                        "last_error": f"Expo receipt error: {error}",
                    },
                    "$pull": {"delivered_tokens": receipt["expo_token"]},
                },
            )
            if requeued.modified_count != 1:
                event = await db.notification_outbox.find_one(
                    {"event_id": receipt["event_id"]},
                    {"_id": 0, "status": 1, "attempts": 1},
                )
                if event and event.get("status") == "processing":
                    await db.push_receipts.update_one(
                        {"ticket_id": ticket_id},
                        {"$set": {"check_after": _now() + timedelta(minutes=2)}},
                    )
                    continue
                if event and int(event.get("attempts") or 0) >= 5:
                    await db.notification_outbox.update_one(
                        {
                            "event_id": receipt["event_id"],
                            "status": {"$in": ["sent", "partial", "retry"]},
                        },
                        {
                            "$set": {
                                "status": "failed",
                                "last_error": f"Expo receipt error: {error or 'unknown'}",
                            }
                        },
                    )
        elif result.get("status") != "ok":
            await db.notification_outbox.update_one(
                {
                    "event_id": receipt["event_id"],
                    "status": {"$in": ["sent", "partial"]},
                },
                {
                    "$set": {"status": "partial"},
                    "$addToSet": {
                        "delivery_failures": {
                            "expo_token": receipt["expo_token"],
                            "error": error or "unknown",
                        }
                    },
                },
            )
        await db.push_receipts.update_one(
            {"ticket_id": ticket_id},
            {
                "$set": {
                    "status": "ok" if result.get("status") == "ok" else "error",
                    "error": error,
                    "checked_at": _now(),
                }
            },
        )
    missing_ids = set(by_id) - set(results)
    if missing_ids:
        await db.push_receipts.update_many(
            {"ticket_id": {"$in": list(missing_ids)}, "status": "pending"},
            {"$set": {"check_after": _now() + timedelta(minutes=5)}},
        )


async def run_push_worker() -> None:
    """Continuously claim outbox events; safe across multiple server workers."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            try:
                await _check_receipts(client)
                now = _now()
                claim_id = uuid.uuid4().hex
                event = await db.notification_outbox.find_one_and_update(
                    {
                        "$or": [
                            {
                                "status": {"$in": ["pending", "retry"]},
                                "next_attempt_at": {"$lte": now},
                            },
                            {
                                "status": "processing",
                                "claimed_at": {"$lte": now - timedelta(minutes=5)},
                            },
                        ]
                    },
                    {
                        "$set": {
                            "status": "processing",
                            "claimed_at": _now(),
                            "claim_id": claim_id,
                        },
                        "$inc": {"attempts": 1},
                    },
                    sort=[("next_attempt_at", 1)],
                    return_document=ReturnDocument.AFTER,
                )
                if event:
                    try:
                        await _deliver_event(client, event)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Push delivery failed: %s", exc)
                        await _retry_or_fail(event, str(exc))
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Push worker pass failed: %s", exc)
            await asyncio.sleep(10)