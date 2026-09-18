"""Read-only bounded report for WatchSmart+ funnel events.

Usage:
    python backend/scripts/plus_funnel_report.py --days 90
"""
import argparse
import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient


EVENTS = {
    "plus_card_viewed",
    "plus_card_clicked",
    "plus_preview_viewed",
    "plus_interest_clicked",
    "plus_interest_removed",
}


async def report(days: int) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    db = client[os.environ["DB_NAME"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await db.plus_events.find(
        {"created_at": {"$gte": cutoff}, "event_name": {"$in": list(EVENTS)}},
        {"_id": 0, "event_name": 1, "user_id": 1, "source_screen": 1, "cohort": 1},
    ).to_list(length=100_000)
    unique = {
        name: {row["user_id"] for row in rows if row.get("event_name") == name}
        for name in EVENTS
    }
    print(f"window_days={days}")
    for name in sorted(EVENTS):
        print(f"{name}.unique_users={len(unique[name])}")
    previews = unique["plus_preview_viewed"]
    interested = unique["plus_interest_clicked"]
    print(f"preview_to_interest_rate={len(interested & previews) / len(previews):.4f}" if previews else "preview_to_interest_rate=null")
    sources = Counter(
        row.get("source_screen", "unknown")
        for row in rows
        if row.get("event_name") in {"plus_preview_viewed", "plus_interest_clicked"}
    )
    cohorts = Counter(
        row.get("cohort", {}).get("signup_period", "unknown")
        for row in rows
        if row.get("event_name") == "plus_interest_clicked"
    )
    print(f"source_counts={dict(sources)}")
    print(f"interest_signup_period_counts={dict(cohorts)}")
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    if args.days < 1 or args.days > 3650:
        raise SystemExit("--days must be between 1 and 3650")
    asyncio.run(report(args.days))