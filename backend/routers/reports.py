"""Issue-report router: users flag inaccurate titles / availability.

Availability data is never perfect — providers change, regions differ, metadata
drifts.  Rather than silently serving wrong data, we give users a way to report
a problem on a title.  Reports land in the `issue_reports` collection for admin
review (see GET /admin/issue-reports) and feed our availability-trust signals.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import db, require_user, find_movie
from providers_util import DEFAULT_REGION
from rate_limit import limiter

router = APIRouter(tags=["reports"])


class ReportReason(str, Enum):
    wrong_provider    = "wrong_provider"     # streams somewhere we don't list / lists wrong
    not_available     = "not_available"      # we say available but it isn't
    missing_title     = "missing_title"      # title/info missing
    bad_metadata      = "bad_metadata"       # wrong year/genre/poster/description
    duplicate         = "duplicate"          # duplicate entry
    other             = "other"


class IssueReportIn(BaseModel):
    reason: ReportReason
    detail: Optional[str] = Field(default=None, max_length=1000)
    # Optional client-supplied provider the report is about (e.g. "netflix").
    provider: Optional[str] = Field(default=None, max_length=64)
    # Honeypot — a hidden field the real UI always leaves empty. Bots that
    # blindly fill every field will populate it, letting us drop the submission.
    website: Optional[str] = Field(default=None, max_length=200)


@router.post("/movies/{movie_id}/report")
@limiter.limit("10/minute")
async def report_issue(
    request: Request,
    movie_id: str,
    payload: IssueReportIn,
    user: dict = Depends(require_user),
):
    """File an issue report against a title for the reporting user's region."""
    # Honeypot tripped → pretend success so bots get no signal, but store nothing.
    if (payload.website or "").strip():
        return {"ok": True, "status": "received"}

    m = find_movie(movie_id) or await db.movies_cache.find_one(
        {"id": movie_id}, {"_id": 0, "title": 1, "type": 1}
    )
    if not m:
        raise HTTPException(404, "Movie not found")

    region = (user.get("country") or DEFAULT_REGION).upper()

    # Light de-dupe: one open report per user+title+reason avoids spam noise.
    existing = await db.issue_reports.find_one({
        "movie_id": movie_id,
        "user_id":  user["user_id"],
        "reason":   payload.reason.value,
        "status":   "open",
    })
    if existing:
        return {"ok": True, "status": "already_reported", "report_id": str(existing.get("_id"))}

    doc = {
        "movie_id":   movie_id,
        "title":      m.get("title"),
        "type":       m.get("type"),
        "user_id":    user["user_id"],
        "reason":     payload.reason.value,
        "detail":     (payload.detail or "").strip() or None,
        "provider":   (payload.provider or "").strip().lower() or None,
        "region":     region,
        "status":     "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.issue_reports.insert_one(doc)
    return {"ok": True, "status": "received", "report_id": str(res.inserted_id)}
