"""Avatar router: profile-photo upload/serve/delete.

Stores processed avatars as binary in a dedicated ``avatars`` collection
(one doc per user, keyed by unique ``user_id``). Uploads are normalized
server-side with Pillow: EXIF-transposed, center-cropped to a square,
resized to 512x512 and re-encoded as JPEG q85. The public GET endpoint
serves the raw bytes so friends can render another user's avatar without
authentication.

``user.picture`` may hold either one of these local avatar URLs
("/api/avatar/<user_id>?v=<ts>") OR an absolute Google account picture URL.
Clients simply render whatever URL is stored, so both are supported.
"""
import io
from datetime import datetime, timezone

from bson import Binary
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from PIL import Image, ImageOps

from core import db, require_user, public_user

router = APIRouter(tags=["avatar"])

# 8 MB hard cap on the uploaded original.
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_TARGET_SIZE = 512
_JPEG_QUALITY = 85

# Accepted upload content types. HEIC is accepted at the transport layer; if
# the installed Pillow build can't decode it, the open below fails and we
# return a clear 415.
_ACCEPTED_CONTENT_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/heic", "image/heif",
}


# Decompression-bomb guard: reject images with more pixels than this BEFORE
# decoding the pixel data (a tiny crafted file can otherwise expand to
# gigabytes in RAM). 40MP comfortably covers modern phone cameras.
_MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = _MAX_PIXELS


def _process_image(raw: bytes) -> bytes:
    """Decode → EXIF-transpose → center-crop square → resize 512 → JPEG q85.

    Raises HTTPException(415) if the bytes are not a decodable image and
    413 if the decoded dimensions exceed the pixel budget.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        # Header-only parse: size is known before any pixel decoding.
        w, h = img.size
        if w * h > _MAX_PIXELS:
            raise HTTPException(status_code=413, detail="Image dimensions too large")
        img.load()
    except HTTPException:
        raise
    except Image.DecompressionBombError:
        raise HTTPException(status_code=413, detail="Image dimensions too large")
    except Exception:
        raise HTTPException(status_code=415, detail="Unsupported or corrupt image")

    # Respect camera orientation, then flatten to RGB (drop alpha/palette).
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Center-crop to a square using the shorter side.
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    img = img.resize((_TARGET_SIZE, _TARGET_SIZE), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue()


@router.post("/user/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
):
    content_type = (file.content_type or "").lower()
    if content_type not in _ACCEPTED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Only image uploads are allowed")

    # Stream in chunks and hard-stop as soon as the cap is exceeded so an
    # oversized body is never fully materialized in memory.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image too large (max 8MB)")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise HTTPException(status_code=415, detail="Empty upload")

    processed = _process_image(raw)

    uid = user["user_id"]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    await db.avatars.update_one(
        {"user_id": uid},
        {"$set": {
            "user_id": uid,
            "data": Binary(processed),
            "content_type": "image/jpeg",
            "updated_at": now_iso,
        }},
        upsert=True,
    )

    # Cache-busting version so clients re-fetch after a new upload.
    picture = f"/api/avatar/{uid}?v={int(now.timestamp())}"
    await db.users.update_one({"user_id": uid}, {"$set": {"picture": picture}})
    return {"picture": picture}


@router.get("/avatar/{user_id}")
async def get_avatar(user_id: str):
    """PUBLIC — serve a user's avatar bytes (avatars are shown to friends)."""
    doc = await db.avatars.find_one({"user_id": user_id}, {"_id": 0})
    if not doc or not doc.get("data"):
        raise HTTPException(status_code=404, detail="No avatar")
    return Response(
        content=bytes(doc["data"]),
        media_type=doc.get("content_type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.delete("/user/avatar")
async def delete_avatar(user: dict = Depends(require_user)):
    uid = user["user_id"]
    await db.avatars.delete_one({"user_id": uid})
    # Simple: clear the picture regardless of whether it was a Google URL.
    await db.users.update_one({"user_id": uid}, {"$set": {"picture": None}})
    return {"picture": None}
