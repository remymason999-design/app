"""WatchSmart+ preview, launch interest, and monetisation foundations."""
import re
import uuid
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import db, require_user
from monetization import (
    MONETIZATION_FLAGS,
    PLUS_EVENT_NAMES,
    PLUS_EVENT_PLATFORMS,
    PLUS_EVENT_SOURCES,
    resolve_account_entitlements,
    sanitized_public_config,
)
from push_notifications import (
    UserDeletionFenceBusy,
    UserNoLongerExists,
    run_under_user_deletion_fence,
)

router = APIRouter(prefix="/monetization", tags=["monetization"])

_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


class PlusInterestIn(BaseModel):
    source_screen: str = Field(default="plus_preview", min_length=1, max_length=40)


class PlusEventIn(BaseModel):
    event_name: str = Field(min_length=1, max_length=40)
    event_id: str = Field(min_length=16, max_length=80)
    source_screen: str = Field(default="unknown", min_length=1, max_length=40)
    platform: str = Field(default="unknown", min_length=1, max_length=16)
    app_version: str | None = Field(default=None, max_length=32)
    test_marker: bool = False


def _source(value: str) -> str:
    value = (value or "unknown").strip().lower()
    return value if value in PLUS_EVENT_SOURCES else "unknown"


def _platform(value: str) -> str:
    value = (value or "unknown").strip().lower()
    return value if value in PLUS_EVENT_PLATFORMS else "unknown"


def _cohort(user: dict) -> dict:
    created = user.get("created_at")
    signup_period = "unknown"
    if isinstance(created, str):
        try:
            signup_period = datetime.fromisoformat(
                created.replace("Z", "+00:00")
            ).strftime("%Y-%m")
        except ValueError:
            pass
    return {
        "signup_period": signup_period,
        "onboarding": (
            "completed" if user.get("onboarding_completed") is True else "incomplete"
        ),
    }


async def record_plus_event(
    *,
    user: dict,
    event_name: str,
    event_id: str | None = None,
    source_screen: str = "unknown",
    platform: str = "unknown",
    app_version: str | None = None,
    test_marker: bool = False,
) -> bool:
    """Write one privacy-minimised event; duplicate event IDs are harmless."""
    if event_name not in PLUS_EVENT_NAMES:
        return False
    event_id = event_id or f"plus_{uuid.uuid4().hex}"
    if not _EVENT_ID_RE.fullmatch(event_id):
        return False
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "event_id": event_id,
        "event_name": event_name,
        "user_id": user["user_id"],
        "created_at": now,
        "platform": _platform(platform),
        "source_screen": _source(source_screen),
        "environment": "development" if os.environ.get("REPLIT_DEPLOYMENT") is None else "production",
        "test_marker": bool(test_marker),
        "cohort": _cohort(user),
    }
    if isinstance(app_version, str) and app_version.strip():
        doc["app_version"] = app_version.strip()[:32]
    try:
        await db.plus_events.insert_one(doc)
        return True
    except DuplicateKeyError:
        return False
    except Exception:
        # Tracking failure must never block navigation or the primary action.
        return False


@router.get("/config")
async def public_monetization_config():
    return sanitized_public_config()


@router.get("/account")
async def monetization_account(user: dict = Depends(require_user)):
    return resolve_account_entitlements(user)


@router.get("/plus/interest")
async def get_plus_interest(user: dict = Depends(require_user)):
    record = await db.plus_interest.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not record:
        return {
            "enabled": bool(MONETIZATION_FLAGS["plus_interest_enabled"]),
            "interested": False,
            "source_screen": None,
            "first_interested_at": None,
            "latest_interested_at": None,
            "latest_removed_at": None,
        }
    return {
        "enabled": bool(MONETIZATION_FLAGS["plus_interest_enabled"]),
        "interested": bool(record.get("interested", False)),
        "source_screen": record.get("source_screen"),
        "first_interested_at": record.get("first_interested_at"),
        "latest_interested_at": record.get("latest_interested_at"),
        "latest_removed_at": record.get("latest_removed_at"),
    }


@router.put("/plus/interest")
async def add_plus_interest(
    payload: PlusInterestIn,
    user: dict = Depends(require_user),
):
    if not MONETIZATION_FLAGS["plus_interest_enabled"]:
        raise HTTPException(409, "WatchSmart+ interest registration is currently unavailable")
    source = _source(payload.source_screen)
    if source == "unknown" and payload.source_screen.strip().lower() != "unknown":
        raise HTTPException(422, "Invalid source screen")
    uid = user["user_id"]
    now = datetime.now(timezone.utc).isoformat()
    owner = f"plus-opt-in:{uid}:{uuid.uuid4().hex}"
    async def write_interest():
        try:
            result = await db.plus_interest.find_one_and_update(
                {"user_id": uid, "interested": {"$ne": True}},
                {
                    "$set": {
                        "user_id": uid,
                        "interested": True,
                        "latest_interested_at": now,
                        "source_screen": source,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"first_interested_at": now},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
        except DuplicateKeyError:
            result = await db.plus_interest.find_one({"user_id": uid}, {"_id": 0})
        if not result:
            result = await db.plus_interest.find_one({"user_id": uid}, {"_id": 0})
        transitioned = bool(result and result.get("latest_interested_at") == now)
        if transitioned:
            await record_plus_event(
                user=user,
                event_name="plus_interest_clicked",
                source_screen=source,
                platform="unknown",
            )
        return result, transitioned
    try:
        result, transitioned = await run_under_user_deletion_fence(
            uid, owner, write_interest, wait_seconds=20, lease_seconds=120
        )
    except UserDeletionFenceBusy:
        raise HTTPException(409, "Please retry joining the WatchSmart+ list")
    except UserNoLongerExists:
        raise HTTPException(401, "Account no longer exists")
    return {
        "interested": bool(result and result.get("interested")),
        "changed": transitioned,
        "message": "You're on the list. We'll let you know when WatchSmart+ is ready.",
    }


@router.delete("/plus/interest")
async def remove_plus_interest(user: dict = Depends(require_user)):
    uid = user["user_id"]
    now = datetime.now(timezone.utc).isoformat()
    owner = f"plus-opt-out:{uid}:{uuid.uuid4().hex}"
    async def remove_interest():
        result = await db.plus_interest.find_one_and_update(
            {"user_id": uid, "interested": True},
            {"$set": {"interested": False, "latest_removed_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        changed = bool(result)
        if changed:
            await record_plus_event(
                user=user,
                event_name="plus_interest_removed",
                source_screen="plus_preview",
                platform="unknown",
            )
        return changed
    try:
        changed = await run_under_user_deletion_fence(
            uid, owner, remove_interest, wait_seconds=20, lease_seconds=120
        )
    except UserDeletionFenceBusy:
        raise HTTPException(503, "Please retry removing WatchSmart+ interest")
    except UserNoLongerExists:
        raise HTTPException(401, "Account no longer exists")
    return {"interested": False, "changed": changed}


@router.post("/events")
async def plus_event(payload: PlusEventIn, user: dict = Depends(require_user)):
    if payload.event_name not in PLUS_EVENT_NAMES:
        raise HTTPException(422, "Unsupported WatchSmart+ event")
    if not _EVENT_ID_RE.fullmatch(payload.event_id):
        raise HTTPException(422, "Invalid event id")
    # Interest conversion/removal are emitted only after their server-side
    # state transition, so clients cannot manufacture conversions.
    if payload.event_name in {"plus_interest_clicked", "plus_interest_removed"}:
        raise HTTPException(422, "Interest events are server generated")
    uid = user["user_id"]
    owner = f"plus-event:{uid}:{uuid.uuid4().hex}"
    async def write_event():
        return await record_plus_event(
            user=user,
            event_name=payload.event_name,
            event_id=payload.event_id,
            source_screen=payload.source_screen,
            platform=payload.platform,
            app_version=payload.app_version,
            test_marker=payload.test_marker,
        )
    try:
        stored = await run_under_user_deletion_fence(
            uid, owner, write_event, wait_seconds=5, lease_seconds=30
        )
    except (UserDeletionFenceBusy, UserNoLongerExists):
        # Tracking must not block navigation or resurrect data after deletion.
        return {"ok": True, "duplicate": False}
    return {"ok": True, "duplicate": not stored}