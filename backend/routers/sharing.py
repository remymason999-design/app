"""Watchlist sharing — share code, friend requests (mutual opt-in), and live compare.

Flow:
  1. Each user has a unique 6-char `share_code` (auto-generated lazily on first
     GET /share/me; share link = `<frontend_origin>/share/<code>`).
  2. User A enters User B's code OR opens the share link. We POST /share/request
     which creates a `pending` request from A → B.
  3. User B sees the request in /share/requests (incoming) and accepts/rejects.
  4. On accept, both user docs gain each other's ID in `watchlist_friends`.
  5. /share/compare/<friend_id> returns overlap, exclusive watchlists, and
     "what you'd both love tonight" recommendations. Polled by client every 3s.

Note: we never expose a friend's email — only display name, picture, and counts.
"""
import os
import secrets
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import (
    db, require_user, get_catalog, movies_by_ids,
)

router = APIRouter(prefix="/share", tags=["sharing"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
CODE_LEN = 6


def _frontend_origin() -> str:
    for o in [x.strip() for x in os.environ.get("ALLOWED_ORIGINS", "").split(",") if x.strip()]:
        if o.startswith("http"):
            return o.rstrip("/")
    return ""


def _gen_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


async def _ensure_code(user: dict) -> str:
    """Return user's share_code, generating + persisting if missing."""
    code = user.get("share_code")
    if code:
        return code
    # Generate unique code
    for _ in range(10):
        candidate = _gen_code()
        if not await db.users.find_one({"share_code": candidate}, {"_id": 1}):
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"share_code": candidate}},
            )
            return candidate
    raise HTTPException(500, "Could not allocate a share code")


def _public_user(u: dict) -> dict:
    return {
        "user_id": u["user_id"],
        "name": u.get("name") or "Friend",
        "picture": u.get("picture"),
        "share_code": u.get("share_code"),
        "watchlist_size": len(u.get("saved") or []),
    }


# --- Models ---------------------------------------------------------------
class CodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


# --- My share info --------------------------------------------------------
@router.get("/me")
async def my_share(user: dict = Depends(require_user)):
    code = await _ensure_code(user)
    origin = _frontend_origin()
    share_url = f"{origin}/share/{code}" if origin else f"/share/{code}"
    return {
        "share_code": code,
        "share_url": share_url,
        "watchlist_size": len(user.get("saved") or []),
    }


@router.post("/lookup")
async def lookup_code(payload: CodeIn, user: dict = Depends(require_user)):
    """Look up a code without committing — used for the 'Send request to X?' confirm step."""
    code = payload.code.upper().strip()
    target = await db.users.find_one({"share_code": code}, {"_id": 0})
    if not target:
        raise HTTPException(404, "No one with that code")
    if target["user_id"] == user["user_id"]:
        raise HTTPException(400, "That's your own code")
    return _public_user(target)


# --- Friend requests ------------------------------------------------------
@router.post("/request")
async def send_request(payload: CodeIn, user: dict = Depends(require_user)):
    code = payload.code.upper().strip()
    target = await db.users.find_one({"share_code": code})
    if not target:
        raise HTTPException(404, "No one with that code")
    if target["user_id"] == user["user_id"]:
        raise HTTPException(400, "You can't friend yourself")

    # Already friends?
    if target["user_id"] in (user.get("watchlist_friends") or []):
        return {"ok": True, "status": "already_friends", "friend": _public_user(target)}

    # Existing pending request from me?
    existing = await db.share_requests.find_one({
        "from_user_id": user["user_id"],
        "to_user_id": target["user_id"],
        "status": "pending",
    })
    if existing:
        return {"ok": True, "status": "already_requested"}

    # Reverse pending? auto-accept (mutual)
    reverse = await db.share_requests.find_one({
        "from_user_id": target["user_id"],
        "to_user_id": user["user_id"],
        "status": "pending",
    })
    if reverse:
        return await _accept(reverse, user)

    now = datetime.now(timezone.utc).isoformat()
    req_id = secrets.token_urlsafe(12)
    await db.share_requests.insert_one({
        "request_id": req_id,
        "from_user_id": user["user_id"],
        "from_name": user.get("name"),
        "to_user_id": target["user_id"],
        "status": "pending",
        "created_at": now,
    })

    # In-app notification for the recipient
    await db.notifications.insert_one({
        "user_id": target["user_id"],
        "title": "New watchlist request",
        "body": f"{user.get('name') or 'Someone'} wants to compare watchlists with you.",
        "kind": "share_request",
        "read": False,
        "created_at": now,
    })

    return {"ok": True, "status": "sent", "request_id": req_id}


@router.get("/requests")
async def list_requests(user: dict = Depends(require_user)):
    incoming = []
    async for r in db.share_requests.find(
        {"to_user_id": user["user_id"], "status": "pending"}, {"_id": 0}
    ).sort("created_at", -1):
        sender = await db.users.find_one({"user_id": r["from_user_id"]}, {"_id": 0}) or {}
        incoming.append({
            "request_id": r["request_id"],
            "from": _public_user(sender) if sender else {"user_id": r["from_user_id"], "name": r.get("from_name")},
            "created_at": r["created_at"],
        })
    outgoing = []
    async for r in db.share_requests.find(
        {"from_user_id": user["user_id"], "status": "pending"}, {"_id": 0}
    ).sort("created_at", -1):
        target = await db.users.find_one({"user_id": r["to_user_id"]}, {"_id": 0}) or {}
        outgoing.append({
            "request_id": r["request_id"],
            "to": _public_user(target) if target else {"user_id": r["to_user_id"]},
            "created_at": r["created_at"],
        })
    return {"incoming": incoming, "outgoing": outgoing}


async def _accept(req: dict, user: dict) -> dict:
    """Mark request accepted and bond both users as friends."""
    a, b = req["from_user_id"], req["to_user_id"]
    await db.share_requests.update_one(
        {"request_id": req["request_id"]},
        {"$set": {"status": "accepted", "responded_at": datetime.now(timezone.utc).isoformat()}},
    )
    await db.users.update_one({"user_id": a}, {"$addToSet": {"watchlist_friends": b}})
    await db.users.update_one({"user_id": b}, {"$addToSet": {"watchlist_friends": a}})
    other_id = a if a != user["user_id"] else b
    other = await db.users.find_one({"user_id": other_id}, {"_id": 0}) or {}
    # Notify the original sender
    await db.notifications.insert_one({
        "user_id": a,
        "title": "Watchlist friend accepted",
        "body": f"{user.get('name') or 'Someone'} accepted — open Compare to see overlap.",
        "kind": "share_accepted",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "status": "accepted", "friend": _public_user(other)}


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str, user: dict = Depends(require_user)):
    req = await db.share_requests.find_one({"request_id": request_id, "status": "pending"})
    if not req or req["to_user_id"] != user["user_id"]:
        raise HTTPException(404, "Request not found")
    return await _accept(req, user)


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, user: dict = Depends(require_user)):
    req = await db.share_requests.find_one({"request_id": request_id, "status": "pending"})
    if not req or req["to_user_id"] != user["user_id"]:
        raise HTTPException(404, "Request not found")
    await db.share_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": "rejected", "responded_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "status": "rejected"}


# --- Friends list ---------------------------------------------------------
@router.get("/friends")
async def list_friends(user: dict = Depends(require_user)):
    ids = user.get("watchlist_friends") or []
    out = []
    if ids:
        async for u in db.users.find({"user_id": {"$in": ids}}, {"_id": 0}):
            out.append(_public_user(u))
    out.sort(key=lambda x: x["name"].lower())
    return out


@router.delete("/friends/{friend_id}")
async def unfriend(friend_id: str, user: dict = Depends(require_user)):
    await db.users.update_one({"user_id": user["user_id"]}, {"$pull": {"watchlist_friends": friend_id}})
    await db.users.update_one({"user_id": friend_id}, {"$pull": {"watchlist_friends": user["user_id"]}})
    return {"ok": True}


# --- Compare watchlists ---------------------------------------------------
def _shared_recommendations(me: dict, them: dict, limit: int = 8) -> List[dict]:
    """Pick titles neither user has interacted with that match both users' tastes."""
    seen = set(
        (me.get("saved") or []) + (me.get("watched") or []) + (me.get("skipped") or []) +
        (them.get("saved") or []) + (them.get("watched") or []) + (them.get("skipped") or [])
    )
    my_w = me.get("genre_weights") or {}
    their_w = them.get("genre_weights") or {}
    my_prefs = set(me.get("genres") or [])
    their_prefs = set(them.get("genres") or [])
    shared_subs = set(me.get("subscriptions") or []) & set(them.get("subscriptions") or [])

    def score(m: dict) -> float:
        mg = set(m.get("genres", []))
        if not mg:
            return -1
        learned = sum(my_w.get(g, 0) for g in mg) + sum(their_w.get(g, 0) for g in mg)
        onboard = len(mg & my_prefs) + len(mg & their_prefs)
        rating = float(m.get("rating") or 0) / 2.0
        recency = 0.5 if (m.get("year") or 0) >= 2023 else 0
        on_shared = 1.0 if shared_subs and (set(m.get("available_on") or []) & shared_subs) else 0
        return rating + learned * 0.5 + onboard * 1.0 + recency + on_shared * 1.5

    candidates = [m for m in get_catalog() if m["id"] not in seen]
    candidates.sort(key=score, reverse=True)
    return [
        {
            "id": m["id"], "title": m["title"], "type": m.get("type"),
            "poster_url": m.get("poster_url"), "rating": m.get("rating"),
            "genres": m.get("genres", [])[:3],
            "available_on": m.get("available_on", []),
        }
        for m in candidates[:limit]
    ]


def _trim_movie(m: dict) -> dict:
    return {
        "id": m["id"], "title": m["title"], "type": m.get("type"),
        "poster_url": m.get("poster_url"), "rating": m.get("rating"),
        "genres": m.get("genres", [])[:3],
        "available_on": m.get("available_on", []),
    }


@router.get("/compare/{friend_id}")
async def compare(friend_id: str, user: dict = Depends(require_user)):
    if friend_id not in (user.get("watchlist_friends") or []):
        raise HTTPException(403, "You're not watchlist friends with that user")
    them = await db.users.find_one({"user_id": friend_id}, {"_id": 0})
    if not them:
        raise HTTPException(404, "Friend not found")

    my_saved = set(user.get("saved") or [])
    their_saved = set(them.get("saved") or [])

    overlap_ids = list(my_saved & their_saved)
    only_me_ids = list(my_saved - their_saved)
    only_them_ids = list(their_saved - my_saved)

    by_id = {m["id"]: m for m in get_catalog()}
    overlap = [_trim_movie(by_id[i]) for i in overlap_ids if i in by_id]
    only_me = [_trim_movie(by_id[i]) for i in only_me_ids if i in by_id]
    only_them = [_trim_movie(by_id[i]) for i in only_them_ids if i in by_id]

    overlap.sort(key=lambda m: m.get("rating") or 0, reverse=True)
    only_me.sort(key=lambda m: m.get("rating") or 0, reverse=True)
    only_them.sort(key=lambda m: m.get("rating") or 0, reverse=True)

    recs = _shared_recommendations(user, them)

    pick_tonight: Optional[dict] = None
    if overlap:
        pick_tonight = overlap[0]
    elif recs:
        pick_tonight = recs[0]

    return {
        "you": _public_user(user),
        "them": _public_user(them),
        "overlap_count": len(overlap),
        "overlap": overlap,
        "only_me": only_me,
        "only_them": only_them,
        "recommendations": recs,
        "pick_tonight": pick_tonight,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
