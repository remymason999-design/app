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
from typing import Optional, List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import (
    db, require_user, get_catalog, movies_by_ids,
)
from sharing import _shared_recommendations
from push_notifications import create_user_notification
from progress import normalize_progress, progress_fingerprint

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

    await create_user_notification(
        target["user_id"],
        title="New watchlist request",
        body=f"{user.get('name') or 'Someone'} wants to compare watchlists with you.",
        kind="share_request",
        push_body="You have a new watchlist request.",
        route="/(tabs)/friends",
        dedupe_key=f"share_request:{req_id}",
    )

    return {"ok": True, "status": "sent", "request_id": req_id}


@router.get("/requests")
async def list_requests(user: dict = Depends(require_user)):
    incoming = []
    async for r in db.share_requests.find(
        {
            "to_user_id": user["user_id"],
            "status": {"$in": ["pending", "accepting"]},
        },
        {"_id": 0},
    ).sort("created_at", -1):
        sender = await db.users.find_one({"user_id": r["from_user_id"]}, {"_id": 0}) or {}
        incoming.append({
            "request_id": r["request_id"],
            "from": _public_user(sender) if sender else {"user_id": r["from_user_id"], "name": r.get("from_name")},
            "created_at": r["created_at"],
        })
    outgoing = []
    async for r in db.share_requests.find(
        {
            "from_user_id": user["user_id"],
            "status": {"$in": ["pending", "accepting"]},
        },
        {"_id": 0},
    ).sort("created_at", -1):
        target = await db.users.find_one({"user_id": r["to_user_id"]}, {"_id": 0}) or {}
        outgoing.append({
            "request_id": r["request_id"],
            "to": _public_user(target) if target else {"user_id": r["to_user_id"]},
            "created_at": r["created_at"],
        })
    return {"incoming": incoming, "outgoing": outgoing}


async def _accept(req: dict, user: dict) -> dict:
    """Idempotently complete an accepted request and both friendship writes."""
    a, b = req["from_user_id"], req["to_user_id"]
    await db.share_requests.update_one(
        {"request_id": req["request_id"], "status": "pending"},
        {"$set": {"status": "accepting"}},
    )
    current = await db.share_requests.find_one({"request_id": req["request_id"]})
    if not current or current.get("status") == "rejected":
        raise HTTPException(409, "This request was rejected")
    if current.get("status") not in {"accepting", "accepted"}:
        raise HTTPException(409, "This request cannot be accepted")
    await db.users.update_one({"user_id": a}, {"$addToSet": {"watchlist_friends": b}})
    await db.users.update_one({"user_id": b}, {"$addToSet": {"watchlist_friends": a}})
    other_id = a if a != user["user_id"] else b
    other = await db.users.find_one({"user_id": other_id}, {"_id": 0}) or {}
    await create_user_notification(
        a,
        title="Watchlist friend accepted",
        body=f"{user.get('name') or 'Someone'} accepted — open Compare to see overlap.",
        kind="share_accepted",
        push_body="Your watchlist request was accepted.",
        route="/(tabs)/friends",
        dedupe_key=f"share_accepted:{req['request_id']}",
    )
    await db.share_requests.update_one(
        {"request_id": req["request_id"], "status": "accepting"},
        {
            "$set": {
                "status": "accepted",
                "responded_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    return {"ok": True, "status": "accepted", "friend": _public_user(other)}


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str, user: dict = Depends(require_user)):
    req = await db.share_requests.find_one({"request_id": request_id})
    if not req or req["to_user_id"] != user["user_id"]:
        raise HTTPException(404, "Request not found")
    return await _accept(req, user)


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, user: dict = Depends(require_user)):
    req = await db.share_requests.find_one({"request_id": request_id})
    if not req or req["to_user_id"] != user["user_id"]:
        raise HTTPException(404, "Request not found")
    if req.get("status") == "rejected":
        return {"ok": True, "status": "already_rejected"}
    result = await db.share_requests.update_one(
        {"request_id": request_id, "status": "pending"},
        {"$set": {"status": "rejected", "responded_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.modified_count != 1:
        current = await db.share_requests.find_one({"request_id": request_id})
        if current and current.get("status") == "rejected":
            return {"ok": True, "status": "already_rejected"}
        raise HTTPException(409, "This request is already being accepted")
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
def _trim_movie(m: dict) -> dict:
    return {
        "id": m["id"], "title": m["title"], "type": m.get("type"),
        "poster_url": m.get("poster_url"), "rating": m.get("rating"),
        "genres": m.get("genres", [])[:3],
        "available_on": m.get("available_on", []),
    }


def _partition(ids: set, other: set, by_id: dict) -> list:
    """Hydrated partition helper used by compare's additive response fields."""
    rows = [_trim_movie(by_id[i]) for i in ids if i in by_id]
    rows.sort(key=lambda m: (-(m.get("rating") or 0), (m.get("title") or "").lower(), m["id"]))
    return rows


@router.get("/compare/{friend_id}")
async def compare(
    friend_id: str,
    view: Optional[Literal["watchlists", "watched", "recs"]] = None,
    scope: Literal["overlap", "only_me", "only_them"] = "overlap",
    page: int = 1,
    page_size: int = 20,
    user: dict = Depends(require_user),
):
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

    # ── Watched + loved comparison ────────────────────────────────────────
    # "Watched by both" uses the watched lists; "loved" comes from each user's
    # watched_feedback sentiment map (loved/liked count as positive, but the
    # dedicated loved sections use the strongest signal: "loved").
    my_watched = set(user.get("watched") or []) | set((user.get("progress") or {}).keys())
    their_watched = set(them.get("watched") or []) | set((them.get("progress") or {}).keys())
    watched_both_ids = list(my_watched & their_watched)

    def _loved_ids(u: dict) -> set:
        fb = u.get("watched_feedback") or {}
        out = set()
        for mid, rec in fb.items():
            if isinstance(rec, dict) and rec.get("sentiment") == "loved":
                out.add(mid)
        return out

    my_loved = _loved_ids(user)
    their_loved = _loved_ids(them)
    both_loved_ids = list(my_loved & their_loved)
    # "Loved by your friend" — things they loved that you haven't watched yet
    # (that's the actionable part: great candidates for you to try).
    loved_by_them_ids = list(their_loved - my_loved - my_watched)

    by_id = {m["id"]: m for m in get_catalog()}

    def _movies(ids: list) -> list:
        out = [_trim_movie(by_id[i]) for i in ids if i in by_id]
        out.sort(key=lambda m: (-(m.get("rating") or 0), (m.get("title") or "").lower(), m["id"]))
        return out

    overlap = _movies(overlap_ids)
    only_me = _movies(only_me_ids)
    only_them = _movies(only_them_ids)
    watched_both = _movies(watched_both_ids)
    both_loved = _movies(both_loved_ids)
    loved_by_them = _movies(loved_by_them_ids)

    # Full additive partitions: unlike the original watchlist-only fields these
    # cover saved and watched sets independently and expose private sentiment /
    # progress only for the two accepted friends.
    def _sentiments(u: dict, ids: set) -> dict:
        fb = u.get("watched_feedback") or {}
        return {mid: (fb[mid].get("sentiment") if isinstance(fb.get(mid), dict) else None)
                for mid in ids if mid in fb}
    def _progress(u: dict, ids: set) -> dict:
        return {mid: normalize_progress((u.get("progress") or {}).get(mid))
                for mid in ids if mid in (u.get("progress") or {})}

    recs = _shared_recommendations(user, them)

    pick_tonight: Optional[dict] = None
    if overlap:
        pick_tonight = overlap[0]
    elif recs:
        pick_tonight = recs[0]

    response = {
        "you": _public_user(user),
        "them": _public_user(them),
        "overlap_count": len(overlap),
        "overlap": overlap,
        "only_me": only_me,
        "only_them": only_them,
        "watched_both": watched_both,
        "both_loved": both_loved,
        "loved_by_them": loved_by_them,
        "saved": {
            "both": overlap,
            "you": _partition(my_saved, their_saved, by_id),
            "friend": _partition(their_saved, my_saved, by_id),
        },
        "watched": {
            "both": watched_both,
            "you": _partition(my_watched, their_watched, by_id),
            "friend": _partition(their_watched, my_watched, by_id),
        },
        "sentiment": {
            "you": _sentiments(user, my_watched),
            "friend": _sentiments(them, their_watched),
        },
        "progress": {
            "you": _progress(user, my_watched),
            "friend": _progress(them, their_watched),
        },
        "recommendations": recs,
        "pick_tonight": pick_tonight,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    if not view:
        return response

    section = (
        recs if view == "recs"
        else response["saved" if view == "watchlists" else "watched"][
            "both" if scope == "overlap" else "you" if scope == "only_me" else "friend"
        ]
    )
    section = list({item["id"]: item for item in section if item.get("id")}.values())
    # Keep pagination bounded and deterministic. Older clients that omit
    # `view` still receive the original full response.
    page_size = max(1, min(int(page_size), 20))
    total_items = len(section)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = max(1, min(int(page), total_pages))
    start = (page - 1) * page_size
    items = section[start:start + page_size]
    item_ids = {item["id"] for item in items}
    return {
        "you": response["you"],
        "them": response["them"],
        "overlap_count": response["overlap_count"],
        "pick_tonight": response["pick_tonight"],
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
        },
        "sentiment": {
            "you": {mid: value for mid, value in response["sentiment"]["you"].items() if mid in item_ids},
            "friend": {mid: value for mid, value in response["sentiment"]["friend"].items() if mid in item_ids},
        },
        "progress": {
            "you": {mid: value for mid, value in response["progress"]["you"].items() if mid in item_ids},
            "friend": {mid: value for mid, value in response["progress"]["friend"].items() if mid in item_ids},
        },
        "synced_at": response["synced_at"],
    }
