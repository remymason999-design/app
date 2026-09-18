"""Notifications router."""
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import db, require_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


class PushDeviceIn(BaseModel):
    expo_token: str = Field(min_length=20, max_length=250)
    installation_id: str = Field(min_length=20, max_length=120)
    unregister_secret: str = Field(min_length=32, max_length=200)
    platform: Literal["ios", "android"]
    app_version: str | None = Field(default=None, max_length=40)


class PushDeviceDeleteIn(BaseModel):
    installation_id: str = Field(min_length=20, max_length=120)
    unregister_secret: str = Field(min_length=32, max_length=200)


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _valid_expo_token(token: str) -> bool:
    return (
        (token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken["))
        and token.endswith("]")
    )


@router.get("/push-status")
async def push_status(installation_id: str, user: dict = Depends(require_user)):
    active = await db.push_devices.count_documents(
        {
            "user_id": user["user_id"],
            "installation_id": installation_id,
            "active": True,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        }
    )
    return {"registered": active > 0}


@router.post("/push-device")
async def register_push_device(payload: PushDeviceIn, user: dict = Depends(require_user)):
    if not _valid_expo_token(payload.expo_token):
        raise HTTPException(400, "Invalid Expo push token")
    now = datetime.now(timezone.utc)
    await db.push_devices.delete_many(
        {
            "expo_token": payload.expo_token,
            "installation_id": {"$ne": payload.installation_id},
        }
    )
    await db.push_devices.update_one(
        {"installation_id": payload.installation_id},
        {
            "$set": {
                "user_id": user["user_id"],
                "expo_token": payload.expo_token,
                "unregister_secret_hash": _secret_hash(payload.unregister_secret),
                "platform": payload.platform,
                "app_version": payload.app_version,
                "active": True,
                "expires_at": now + timedelta(days=365),
                "last_seen_at": now,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
            "$unset": {"disabled_reason": ""},
        },
        upsert=True,
    )
    return {"ok": True}


@router.delete("/push-device")
async def unregister_push_device(payload: PushDeviceDeleteIn):
    result = await db.push_devices.delete_one(
        {
            "installation_id": payload.installation_id,
            "unregister_secret_hash": _secret_hash(payload.unregister_secret),
        }
    )
    return {"ok": True, "removed": result.deleted_count > 0}


@router.get("")
async def list_notifications(user: dict = Depends(require_user)):
    out = []
    async for n in db.notifications.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(30):
        out.append(n)
    unread = await db.notifications.count_documents({"user_id": user["user_id"], "read": False})
    return {"items": out, "unread": unread}


@router.post("/read-all")
async def mark_all_read(user: dict = Depends(require_user)):
    r = await db.notifications.update_many(
        {"user_id": user["user_id"], "read": False},
        {"$set": {"read": True}},
    )
    return {"updated": r.modified_count}


@router.delete("/clear-all")
async def clear_all_notifications(user: dict = Depends(require_user)):
    """Delete all notifications for the current user."""
    result = await db.notifications.delete_many({"user_id": user["user_id"]})
    return {"deleted": result.deleted_count}


@router.delete("/{notif_id}")
async def delete_notification(notif_id: str, user: dict = Depends(require_user)):
    """Delete a single notification by its notification_id field."""
    result = await db.notifications.delete_one(
        {"notification_id": notif_id, "user_id": user["user_id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}
