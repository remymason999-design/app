"""Approval-gated, auditable WatchSmart+ launch notifications."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import db
from email_service import _wrapper, send_email
from push_notifications import (
    UserDeletionFenceBusy,
    UserNoLongerExists,
    acquire_push_delivery_lock,
    create_user_notification,
    release_push_delivery_lock,
    run_under_user_deletion_fence,
)

CAMPAIGN_ID = "watchsmart-plus-launch"
CHANNELS = ("email", "push")

# Resend deduplicates repeated Idempotency-Key requests for 24 hours. If a
# provider_error is ambiguous (Resend may have accepted the send before the
# error surfaced), retrying past that window would no longer be deduplicated
# and could send a second launch email. Retries are only safe strictly inside
# a margin under that window; past it we stop and require manual review
# rather than risk a duplicate send.
EMAIL_IDEMPOTENCY_SAFE_RETRY_WINDOW = timedelta(hours=20)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def launch_state() -> dict:
    state = await db.plus_launch_state.find_one({"campaign_id": CAMPAIGN_ID}, {"_id": 0})
    return state or {
        "campaign_id": CAMPAIGN_ID,
        "status": "draft",
        "approved_at": None,
        "revoked_at": None,
    }


async def set_launch_approval(*, approved: bool, admin_user_id: str) -> dict:
    now = _now()
    update = {
        "$set": {
            "campaign_id": CAMPAIGN_ID,
            "status": "approved" if approved else "draft",
            "updated_at": now,
            "approved_at" if approved else "revoked_at": now,
            "approved_by" if approved else "revoked_by": admin_user_id,
        }
    }
    if approved:
        update["$unset"] = {"revoked_at": "", "revoked_by": ""}
    else:
        update["$unset"] = {"approved_at": "", "approved_by": ""}
    owner = f"plus-approval:{admin_user_id}:{uuid.uuid4().hex}"
    if not await acquire_push_delivery_lock(
        f"campaign:{CAMPAIGN_ID}", owner, wait_seconds=20, lease_seconds=120
    ):
        raise RuntimeError("Launch delivery is currently busy")
    try:
        return await db.plus_launch_state.find_one_and_update(
            {"campaign_id": CAMPAIGN_ID},
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
    finally:
        await release_push_delivery_lock(f"campaign:{CAMPAIGN_ID}", owner)


async def _assert_approved() -> None:
    state = await launch_state()
    if state.get("status") != "approved":
        raise PermissionError("WatchSmart+ launch delivery has not been approved")


async def _claim_delivery(user_id: str, channel: str) -> dict | None:
    """Create or reclaim one channel delivery. Sent/cancelled rows stay terminal."""
    now = _now()
    key = f"{CAMPAIGN_ID}:{channel}:{user_id}"
    try:
        await db.plus_launch_deliveries.insert_one({
            "delivery_key": key,
            "campaign_id": CAMPAIGN_ID,
            "user_id": user_id,
            "channel": channel,
            "status": "pending",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
        })
    except DuplicateKeyError:
        pass
    claim_id = uuid.uuid4().hex
    return await db.plus_launch_deliveries.find_one_and_update(
        {
            "delivery_key": key,
            "$or": [
                {"status": {"$in": ["pending", "retry"]}},
                {
                    "status": "processing",
                    "claimed_at": {"$lte": now - timedelta(minutes=5)},
                },
            ],
        },
        {
            "$set": {
                "status": "processing",
                "claim_id": claim_id,
                "claimed_at": now,
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )


async def _finish(delivery: dict, status: str, **fields) -> None:
    update = {
        "$set": {"status": status, "updated_at": _now(), **fields},
        "$unset": {"claim_id": "", "claimed_at": ""},
    }
    await db.plus_launch_deliveries.update_one(
        {
            "delivery_key": delivery["delivery_key"],
            "status": "processing",
            "claim_id": delivery["claim_id"],
        },
        update,
    )


async def _still_interested(user_id: str) -> bool:
    return bool(await db.plus_interest.find_one(
        {"user_id": user_id, "interested": True},
        {"_id": 1},
    ))


async def dispatch_channel(channel: Literal["email", "push"], limit: int = 100) -> dict:
    """Dispatch a bounded channel batch. Safe to rerun after partial failure."""
    if channel not in CHANNELS:
        raise ValueError("Unsupported launch channel")
    await _assert_approved()
    summary = {"channel": channel, "eligible": 0, "sent": 0, "cancelled": 0, "retry": 0, "failed": 0}
    cursor = db.plus_interest.find(
        {"interested": True},
        {"_id": 0, "user_id": 1},
    ).sort("user_id", 1)
    attempted = 0
    batch_limit = max(1, min(limit, 500))
    async for interest in cursor:
        summary["eligible"] += 1
        if attempted >= batch_limit:
            break
        user_id = interest["user_id"]
        campaign_owner = f"plus-dispatch:{channel}:{uuid.uuid4().hex}"
        user_owner = f"{campaign_owner}:{user_id}"
        campaign_locked = False
        delivery = None
        try:
            if not await acquire_push_delivery_lock(
                f"campaign:{CAMPAIGN_ID}",
                campaign_owner,
                wait_seconds=20,
                lease_seconds=120,
            ):
                raise RuntimeError("Launch approval lock is busy")
            campaign_locked = True
            async def deliver_to_user():
                nonlocal attempted, delivery
                await _assert_approved()
                if not await _still_interested(user_id):
                    return
                delivery = await _claim_delivery(user_id, channel)
                if not delivery:
                    return
                attempted += 1
                if channel == "email":
                    created_at = delivery.get("created_at")
                    if isinstance(created_at, datetime) and _now() - created_at > (
                        EMAIL_IDEMPOTENCY_SAFE_RETRY_WINDOW
                    ):
                        # Retrying after Resend's idempotency window risks a
                        # duplicate launch email and requires reconciliation.
                        await _finish(
                            delivery, "failed", outcome="idempotency_window_expired"
                        )
                        summary["failed"] += 1
                        return
                    user = await db.users.find_one(
                        {"user_id": user_id},
                        {"_id": 0, "email": 1},
                    )
                    email = (user or {}).get("email")
                    if not email:
                        await _finish(delivery, "cancelled", outcome="no_email")
                        summary["cancelled"] += 1
                        return
                    body = (
                        "<p>WatchSmart+ is ready.</p>"
                        "<p>Open WatchSmart to see what is available.</p>"
                        "<p>You received this one-time update because you asked us "
                        "to let you know. You can remove your interest in WatchSmart+ "
                        "from your profile at any time.</p>"
                    )
                    ok = await send_email(
                        to=email,
                        subject="WatchSmart+ is ready",
                        html=_wrapper("WatchSmart+ is ready", body),
                        text=(
                            "WatchSmart+ is ready. Open WatchSmart to see what is available. "
                            "You received this update because you asked us to let you know."
                        ),
                        idempotency_key=delivery["delivery_key"],
                    )
                    if not ok:
                        await _finish(delivery, "retry", outcome="provider_error")
                        summary["retry"] += 1
                        return
                    await _finish(delivery, "sent", outcome="accepted")
                else:
                    await create_user_notification(
                        user_id,
                        title="WatchSmart+ is ready",
                        body="WatchSmart+ is now ready. Open WatchSmart to find out more.",
                        kind="plus_launch",
                        push_title="WatchSmart+ is ready",
                        push_body="Open WatchSmart to find out more.",
                        route="/plus",
                        dedupe_key=delivery["delivery_key"],
                        consent_kind="plus_interest",
                        campaign_id=CAMPAIGN_ID,
                        require_push_queue=True,
                    )
                    await _finish(delivery, "sent", outcome="queued")
                summary["sent"] += 1
            await run_under_user_deletion_fence(
                user_id,
                user_owner,
                deliver_to_user,
                wait_seconds=20,
                lease_seconds=120,
            )
        except (UserDeletionFenceBusy, UserNoLongerExists):
            continue
        except Exception:
            if delivery is not None:
                await _finish(delivery, "retry", outcome="internal_error")
                summary["retry"] += 1
        finally:
            if campaign_locked:
                await release_push_delivery_lock(
                    f"campaign:{CAMPAIGN_ID}", campaign_owner
                )
    return summary


async def delivery_metrics() -> dict:
    """Return aggregate outcomes only; never profile or contact data."""
    result = {}
    for channel in CHANNELS:
        counts = {}
        async for row in db.plus_launch_deliveries.find(
            {"campaign_id": CAMPAIGN_ID, "channel": channel},
            {"_id": 0, "status": 1, "outcome": 1},
        ):
            key = f"{row.get('status', 'unknown')}:{row.get('outcome', 'none')}"
            counts[key] = counts.get(key, 0) + 1
        result[channel] = counts
    push_outbox = {}
    async for row in db.notification_outbox.find(
        {"campaign_id": CAMPAIGN_ID},
        {"_id": 0, "status": 1, "delivery": 1},
    ):
        key = f"{row.get('status', 'unknown')}:{row.get('delivery', 'none')}"
        push_outbox[key] = push_outbox.get(key, 0) + 1
    result["push_outbox"] = push_outbox
    result["currently_opted_in"] = await db.plus_interest.count_documents({"interested": True})
    result["removed"] = await db.plus_interest.count_documents({"interested": False})
    return result