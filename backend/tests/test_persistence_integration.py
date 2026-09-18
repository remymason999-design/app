from __future__ import annotations

# Tell pytest to skip this module — it's a standalone runnable script, not a
# pytest test suite. The `test_*` functions take positional args (uid) by design
# and would error under pytest collection. Run directly with python3 instead.
__test__ = False
collect_ignore_glob = ["*"]

"""End-to-end persistence integration test.

Validates that ALL user data survives a full session lifecycle:

  1. Sign up (or seed) a user.
  2. Apply preferences (subscriptions, country, content_type, excluded_*).
  3. Apply Discover toggles (include_other_services, include_rent_buy).
  4. Perform swipe actions (save / watched / skip).
  5. Update onboarding state.
  6. Re-fetch the user document and assert every field persisted.
  7. Simulate a "log out and back in" by re-reading from MongoDB.

This is the safety net for §4 of the QA list — proves users won't lose data.

Run:
    cd backend && python3 tests/test_persistence_integration.py

Exits non-zero on any assertion failure.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Allow running as a script without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db, public_user, _PUBLIC_STRIP                # noqa: E402


# ── Test harness helpers ──────────────────────────────────────────────────────

PASS = "✓"
FAIL = "✗"
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}{(' — ' + detail) if detail else ''}")
        _failures.append(label)


# ── Test fixtures ─────────────────────────────────────────────────────────────

async def _seed_user(uid: str) -> None:
    """Create a clean test user with known starting state."""
    await db.users.insert_one({
        "user_id":       uid,
        "email":         f"{uid}@persistence.test",
        "name":          "Persistence Test",
        "auth_provider": "password",
        # All default fields so the test mirrors a real signup
        "saved": [], "watched": [], "skipped": [],
        "onboarding_rated": [], "recently_shown": [],
        "subscriptions": [], "genres": [], "moods": [],
        "excluded_categories": [], "excluded_genres": [],
        "content_type": "both", "country": "GB",
        "genre_weights": {}, "language_weights": {}, "decade_weights": {},
        "theme_weights": {}, "tone_weights": {}, "pacing_weights": {},
        "type_weights": {},
        "auto_blocked_languages": [], "auto_blocked_decades": [],
        "include_other_services": False,
        "include_rent_buy":       False,
        "show_international":     True,
        "year_range":             "any",
        "onboarding_completed":   False,
        "exploration_weight":     0.5,
        "role":                   "user",
        "created_at":             datetime.now(timezone.utc).isoformat(),
    })


async def _cleanup(uid: str) -> None:
    await db.users.delete_one({"user_id": uid})
    await db.user_actions.delete_many({"user_id": uid})


# ── Test cases ────────────────────────────────────────────────────────────────

async def test_preferences_persist(uid: str) -> None:
    print("\n[1] Preferences persistence")
    # Apply a representative cross-section of preference fields.
    update = {
        "subscriptions":           ["netflix", "amazon_prime", "disney_plus"],
        "genres":                  ["Horror", "Thriller"],
        "excluded_categories":     ["family", "anime"],
        "excluded_genres":         ["Romance"],
        "content_type":            "movie",
        "country":                 "US",
        "show_international":      False,
        "year_range":              "last_10",
        "include_other_services":  True,
        "include_rent_buy":        True,
        "onboarding_completed":    True,
    }
    await db.users.update_one({"user_id": uid}, {"$set": update})

    # Re-read the fresh document — this simulates "log out and back in".
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    check("subscriptions persist",          fresh.get("subscriptions") == update["subscriptions"])
    check("genres persist",                 fresh.get("genres") == update["genres"])
    check("excluded_categories persist",    fresh.get("excluded_categories") == update["excluded_categories"])
    check("excluded_genres persist",        fresh.get("excluded_genres") == update["excluded_genres"])
    check("content_type persists",          fresh.get("content_type") == "movie")
    check("country persists",               fresh.get("country") == "US")
    check("show_international persists",    fresh.get("show_international") is False)
    check("year_range persists",            fresh.get("year_range") == "last_10")
    check("include_other_services persists", fresh.get("include_other_services") is True)
    check("include_rent_buy persists",      fresh.get("include_rent_buy") is True)
    check("onboarding_completed persists",  fresh.get("onboarding_completed") is True)


async def test_swipe_actions_persist(uid: str) -> None:
    print("\n[2] Swipe-action persistence (saved / watched / skipped)")
    # Mirror what /user/action does on the backend.
    await db.users.update_one({"user_id": uid}, {
        "$addToSet": {
            "saved":   {"$each": ["movie_a", "movie_b"]},
            "watched": {"$each": ["movie_c"]},
            "skipped": {"$each": ["movie_d", "movie_e", "movie_f"]},
        },
        "$inc": {
            "genre_weights.Horror":     1.5,
            "genre_weights.Thriller":   1.0,
            "genre_weights.Comedy":    -0.8,
            "language_weights.ja":     -3.0,
            "decade_weights.1980s":    -2.0,
            "tone_weights.dark":        1.2,
        },
    })

    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    check("saved list persists",      set(fresh.get("saved") or []) == {"movie_a", "movie_b"})
    check("watched list persists",    set(fresh.get("watched") or []) == {"movie_c"})
    check("skipped list persists",    set(fresh.get("skipped") or []) == {"movie_d", "movie_e", "movie_f"})

    gw = fresh.get("genre_weights") or {}
    check("positive genre_weight persists",  gw.get("Horror") == 1.5)
    check("negative genre_weight persists",  gw.get("Comedy") == -0.8)
    check("language_weight persists",        (fresh.get("language_weights") or {}).get("ja") == -3.0)
    check("decade_weight persists",          (fresh.get("decade_weights") or {}).get("1980s") == -2.0)
    check("tone_weight persists",            (fresh.get("tone_weights") or {}).get("dark") == 1.2)


async def test_recently_shown_persists(uid: str) -> None:
    print("\n[3] Recently-shown LRU persistence")
    shown = [{"id": f"movie_{i}", "ts": datetime.now(timezone.utc).isoformat()} for i in range(5)]
    await db.users.update_one({"user_id": uid}, {"$set": {"recently_shown": shown}})
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    check("recently_shown persists with correct length", len(fresh.get("recently_shown") or []) == 5)
    check("recently_shown items have ids",
          all("id" in r for r in fresh.get("recently_shown") or []))


async def test_auto_blocklist_persists(uid: str) -> None:
    print("\n[4] Auto-blocklist persistence")
    await db.users.update_one({"user_id": uid}, {
        "$addToSet": {
            "auto_blocked_languages": "ja",
            "auto_blocked_decades":   "1970s",
        },
    })
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    check("auto_blocked_languages persists", "ja" in (fresh.get("auto_blocked_languages") or []))
    check("auto_blocked_decades persists",   "1970s" in (fresh.get("auto_blocked_decades") or []))


async def test_public_user_strips_internals(uid: str) -> None:
    print("\n[5] public_user() correctly hides backend-only fields")
    raw = await db.users.find_one({"user_id": uid}, {"_id": 0})
    pub = public_user(dict(raw))
    for f in _PUBLIC_STRIP:
        check(f"public_user strips '{f}'", f not in pub)
    # But user-facing fields must still be present
    for keep in ("subscriptions", "saved", "watched", "skipped",
                 "include_other_services", "include_rent_buy",
                 "language_weights", "decade_weights"):
        check(f"public_user keeps '{keep}'", keep in pub)


async def test_atomic_concurrent_writes(uid: str) -> None:
    """Confirm that concurrent $inc and $addToSet ops don't lose data.
    Real users may swipe quickly; the backend must use atomic ops, not read-modify-write.
    """
    print("\n[6] Concurrent writes are atomic (no lost updates)")
    # Reset the genre weight first
    await db.users.update_one({"user_id": uid}, {"$set": {"genre_weights.Action": 0.0}})

    async def _bump():
        await db.users.update_one({"user_id": uid}, {"$inc": {"genre_weights.Action": 1.0}})

    # 20 concurrent increments — final value should be exactly 20.0
    await asyncio.gather(*(_bump() for _ in range(20)))
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    final = (fresh.get("genre_weights") or {}).get("Action")
    check(f"20 concurrent $inc ops summed correctly (got {final})", final == 20.0)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    uid = f"persist_test_{uuid.uuid4().hex[:8]}"
    print("═" * 64)
    print(f"  Persistence Integration Test  (user: {uid})")
    print("═" * 64)

    try:
        await _seed_user(uid)
        await test_preferences_persist(uid)
        await test_swipe_actions_persist(uid)
        await test_recently_shown_persists(uid)
        await test_auto_blocklist_persists(uid)
        await test_public_user_strips_internals(uid)
        await test_atomic_concurrent_writes(uid)
    finally:
        await _cleanup(uid)

    print("\n" + "─" * 64)
    if _failures:
        print(f"  RESULT: {len(_failures)} failure(s)")
        for f in _failures:
            print(f"    {FAIL}  {f}")
        print("═" * 64)
        return 1

    print("  RESULT: All persistence checks passed ✓")
    print("═" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
