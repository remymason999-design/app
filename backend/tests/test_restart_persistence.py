from __future__ import annotations

# Standalone runnable script, not a pytest suite (test_* fns take args / hit a
# live server + restart mongod). Run directly with python3.
__test__ = False
collect_ignore_glob = ["*"]

"""Restart-persistence integration test — the beta data-safety net.

Proves a complete user session survives a REAL MongoDB process restart by
driving the actual HTTP API (so JWT auth + every persistence path is exercised
end to end):

    1. create account            (POST /auth/register)
    2. onboard                   (PUT /user/preferences + POST /onboarding/complete)
    3. swipe 50 titles           (POST /user/action: 5 save, 10 reject, 35 watched)
    4. snapshot state            (GET /auth/me)
    5. RESTART mongod            (shutdown + relaunch on the persistent dbPath)
    6. log back in               (POST /auth/login)
    7. verify EVERYTHING restored (account, onboarding, subscriptions, saved,
       disliked, watched, recommendation weights)

It also asserts the root-cause fix directly: mongod's dbPath must NOT be under
/tmp (which is wiped on container recycle).

Run (with the app workflow running):
    cd backend && python3 tests/test_restart_persistence.py

Exits non-zero on any assertion failure.
"""
import asyncio
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx                                                     # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient              # noqa: E402

BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000/api")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

PASS, FAIL = "✓", "✗"
_failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {PASS if cond else FAIL}  {label}" + (f" — {detail}" if (detail and not cond) else ""))
    if not cond:
        _failures.append(label)


# ── mongod control ────────────────────────────────────────────────────────────

async def _get_dbpath(client: AsyncIOMotorClient) -> str | None:
    opts = await client.admin.command("getCmdLineOpts")
    return (opts.get("parsed", {}).get("storage", {}) or {}).get("dbPath")


def _mongod_running() -> bool:
    return subprocess.run(["pgrep", "-x", "mongod"], capture_output=True).returncode == 0


def _port_free(port: int = 27017) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def _restart_mongod(dbpath: str) -> None:
    """Cleanly shut down mongod and relaunch it on the same persistent dbPath.

    This is the real 'restart' the test hinges on — if data only lived in
    process memory or an ephemeral path, it would not survive this.
    """
    subprocess.run(["mongod", "--shutdown", "--dbpath", dbpath],
                   capture_output=True, check=False)
    for _ in range(40):
        if not _mongod_running() and _port_free():
            break
        time.sleep(0.5)
    res = subprocess.run(
        ["mongod", "--dbpath", dbpath, "--fork",
         "--logpath", "/tmp/mongodb.log", "--port", "27017"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"mongod relaunch failed (rc={res.returncode}): "
            f"{res.stdout.strip()} {res.stderr.strip()}"
        )


async def _wait_for_mongo(url: str, timeout_s: int = 30) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        c = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1000)
        try:
            await c.admin.command("ping")
            return True
        except Exception:
            await asyncio.sleep(0.5)
        finally:
            c.close()
    return False


# ── HTTP helpers ────────────────────────────────────────────────────────────

async def _catalog_ids(db, want: int) -> list[str]:
    """Source `want` distinct, valid movie ids straight from the catalogue.

    The test verifies *persistence*, not the recommender's pool size — so we
    take ids directly from movies_cache (guaranteed actionable) instead of
    relying on /discover, which is intentionally limited per-user by genre/
    provider filters + the recently-shown cooldown.
    """
    docs = await db.movies_cache.find({"id": {"$ne": None}}, {"id": 1}).limit(want * 2).to_list(length=want * 2)
    seen: set[str] = set()
    ids: list[str] = []
    for d in docs:
        mid = d.get("id")
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
        if len(ids) >= want:
            break
    return ids


# ── Main flow ─────────────────────────────────────────────────────────────────

async def main() -> int:
    print("═" * 64)
    print("  Restart-Persistence Integration Test")
    print("═" * 64)

    mongo = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = mongo[DB_NAME]

    email = f"restart_test_{uuid.uuid4().hex[:8]}@watchsmart-qa.com"
    password = "Sup3r-Secret-Pw!"
    uid_holder: dict = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # ── Root-cause guard: dbPath must be persistent, not /tmp ──────────
            print("\n[0] Root-cause check — mongod dbPath is persistent")
            dbpath = await _get_dbpath(mongo)
            check(f"dbPath is not under /tmp (got: {dbpath})",
                  bool(dbpath) and not dbpath.startswith("/tmp"), dbpath or "unknown")

            # ── 1. Create account ─────────────────────────────────────────────
            print("\n[1] Create account")
            r = await client.post(f"{BASE}/auth/register", json={
                "email": email, "name": "Restart Test",
                "password": password, "accept_terms": True,
            })
            check("register returns 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
            if r.status_code != 200:
                return 1
            tok = r.json()["access_token"]
            uid_holder["uid"] = r.json()["user"]["user_id"]
            headers = {"Authorization": f"Bearer {tok}"}

            # ── 2. Onboard ────────────────────────────────────────────────────
            print("\n[2] Onboard (preferences + complete)")
            subs = ["netflix", "prime_video", "disney_plus"]
            genres = ["Horror", "Thriller"]
            r = await client.put(f"{BASE}/user/preferences", headers=headers, json={
                "services": subs, "genres": genres,
                "content_type": "both", "country": "GB",
            })
            check("preferences saved (200)", r.status_code == 200, f"status={r.status_code}")
            r = await client.post(f"{BASE}/onboarding/complete", headers=headers, json={})
            check("onboarding/complete (200)", r.status_code == 200, f"status={r.status_code}")

            # ── 3. Swipe 50 (5 save, 10 reject, 35 watched) ───────────────────
            print("\n[3] Swipe 50 titles")
            ids = await _catalog_ids(db, 50)
            check(f"sourced 50 distinct movie ids from catalog (got {len(ids)})", len(ids) >= 50)
            if len(ids) < 50:
                return 1
            save_ids = ids[:5]
            reject_ids = ids[5:15]
            watched_ids = ids[15:50]

            async def act(mid: str, action: str):
                rr = await client.post(f"{BASE}/user/action", headers=headers,
                                       json={"movie_id": mid, "action": action})
                return rr.status_code

            for mid in save_ids:
                await act(mid, "save")
            for mid in reject_ids:
                await act(mid, "skip")
            for mid in watched_ids:
                await act(mid, "watched")
            print(f"     saved={len(save_ids)} rejected={len(reject_ids)} watched={len(watched_ids)}")

            # ── 4. Snapshot pre-restart state ─────────────────────────────────
            print("\n[4] Snapshot state (GET /auth/me)")
            r = await client.get(f"{BASE}/auth/me", headers=headers)
            check("me returns 200", r.status_code == 200, f"status={r.status_code}")
            before = r.json()
            snap = {
                "onboarding_completed": before.get("onboarding_completed"),
                "subscriptions": set(before.get("subscriptions") or []),
                "genres": set(before.get("genres") or []),
                "saved": set(before.get("saved") or []),
                "skipped": set(before.get("skipped") or []),
                "watched": set(before.get("watched") or []),
                "genre_weights": before.get("genre_weights") or {},
                "tone_weights": before.get("tone_weights") or {},
            }
            check("onboarding_completed is True before restart", snap["onboarding_completed"] is True)
            check("5 saved before restart", len(snap["saved"]) == 5, str(len(snap["saved"])))
            check("10 rejected before restart", len(snap["skipped"]) == 10, str(len(snap["skipped"])))
            check("35 watched before restart", len(snap["watched"]) == 35, str(len(snap["watched"])))
            check("recommendation weights learned before restart",
                  len(snap["genre_weights"]) > 0, "no genre_weights")

        except Exception as exc:  # noqa: BLE001
            print(f"  {FAIL}  pre-restart phase crashed: {exc!r}")
            _failures.append("pre-restart phase")
            await _cleanup(db, email)
            mongo.close()
            return 1

        # ── 5. RESTART mongod ────────────────────────────────────────────────
        print("\n[5] Restart MongoDB (real process restart)")
        try:
            _restart_mongod(dbpath)
            up = await _wait_for_mongo(MONGO_URL, timeout_s=30)
            check("mongod came back up after restart", up)
            if not up:
                return 1
        except Exception as exc:  # noqa: BLE001
            check("mongod restart succeeded", False, repr(exc))
            return 1

        # ── 6 & 7. Log back in and verify everything restored ────────────────
        print("\n[6] Log back in (POST /auth/login)")
        async with httpx.AsyncClient(timeout=30.0) as client2:
            r = await client2.post(f"{BASE}/auth/login", json={"email": email, "password": password})
            check("login after restart (200)", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
            if r.status_code != 200:
                await _cleanup(db, email)
                mongo.close()
                return 1
            tok2 = r.json()["access_token"]
            headers2 = {"Authorization": f"Bearer {tok2}"}

            print("\n[7] Verify ALL state restored after restart")
            r = await client2.get(f"{BASE}/auth/me", headers=headers2)
            check("me after restart (200)", r.status_code == 200)
            after = r.json()

            check("account persisted (email matches)", after.get("email") == email)
            check("onboarding survived restart", after.get("onboarding_completed") is True)
            check("subscriptions survived restart",
                  set(after.get("subscriptions") or []) == snap["subscriptions"],
                  str(after.get("subscriptions")))
            check("genres survived restart",
                  set(after.get("genres") or []) == snap["genres"])
            check("saved / watchlist survived restart (5)",
                  set(after.get("saved") or []) == snap["saved"])
            check("disliked / rejected survived restart (10)",
                  set(after.get("skipped") or []) == snap["skipped"])
            check("watched survived restart (35)",
                  set(after.get("watched") or []) == snap["watched"])
            check("recommendation weights survived restart",
                  (after.get("genre_weights") or {}) == snap["genre_weights"],
                  "genre_weights differ")
            check("tone weights survived restart",
                  (after.get("tone_weights") or {}) == snap["tone_weights"])

        await _cleanup(db, email)
    mongo.close()

    print("\n" + "─" * 64)
    if _failures:
        print(f"  RESULT: {len(_failures)} failure(s)")
        for f in _failures:
            print(f"    {FAIL}  {f}")
        print("═" * 64)
        return 1
    print("  RESULT: All restart-persistence checks passed ✓")
    print("═" * 64)
    return 0


async def _cleanup(db, email: str) -> None:
    user = await db.users.find_one({"email": email}, {"user_id": 1})
    if user:
        uid = user["user_id"]
        await db.users.delete_one({"user_id": uid})
        await db.user_actions.delete_many({"user_id": uid})
        await db.notifications.delete_many({"user_id": uid})


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
