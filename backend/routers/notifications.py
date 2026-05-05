"""Notifications router."""
from fastapi import APIRouter, Depends

from core import db, require_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


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
