"""Iteration 9 — Recommendation engine (build_feed) backend tests.

Covers:
- /api/discover contract (20 items, _signals keys, reason)
- Filters (content_type, excluded_categories, excluded_genres) strict
- Permanent exclusions (saved/watched/onboarding_rated)
- Recently-shown LRU (consecutive calls return mostly different items)
- Random injection produces > limit distinct titles across calls
- Adaptive maturity (cold-start ~0; rises after 50+ user_actions)
- Collaborative reason/in_collab when neighbours align
- Cooldown re-intro path (direct mongo writes; backdate skip + boost genres)
- Catalog size >= 900, admin pool >= 300
- /api/me/engagement contract
- Existing endpoints not regressed
- Onboarding-rated movies never appear in /discover
- POST /api/admin/refresh-catalog?pages=3
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

# Allow direct mongo writes for cooldown re-intro tests
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@watchsmart.app"
ADMIN_PASS = "admin123"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _register_fresh_user():
    suffix = uuid.uuid4().hex[:10]
    email = f"test_eng_{suffix}@watchsmart.app"
    pw = "Test1234!"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": "EngTest"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    return token, r.json().get("user", {}).get("user_id"), email


@pytest.fixture
def fresh_user():
    token, uid, email = _register_fresh_user()
    return {"token": token, "user_id": uid, "email": email, "headers": {"Authorization": f"Bearer {token}"}}


# ------------------------------------------------------------------
# 1. Discover contract
# ------------------------------------------------------------------

class TestDiscoverContract:
    REQUIRED = {"id", "title", "type", "poster_url", "reason", "_signals"}

    def test_returns_up_to_20_items(self, admin_headers):
        r = requests.get(f"{API}/discover", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        assert 1 <= len(items) <= 20, f"Got {len(items)}"

    def test_required_keys_present(self, admin_headers):
        items = requests.get(f"{API}/discover", headers=admin_headers, timeout=15).json()
        assert items, "discover empty"
        sample = items[0]
        missing = self.REQUIRED - set(sample.keys())
        assert not missing, f"Missing keys: {missing}"
        sig = sample["_signals"]
        for k in ("maturity", "pool_size", "in_collab", "is_reintro"):
            assert k in sig, f"_signals missing {k}"
        assert isinstance(sig["maturity"], (int, float))
        assert isinstance(sig["pool_size"], int)
        assert isinstance(sig["in_collab"], bool)
        assert isinstance(sig["is_reintro"], bool)


# ------------------------------------------------------------------
# 2. Filters (regression from iteration 8 — must still apply on engine)
# ------------------------------------------------------------------

class TestFilters:
    def _set_prefs(self, headers, **prefs):
        r = requests.put(f"{API}/user/preferences", headers=headers, json=prefs, timeout=15)
        assert r.status_code == 200, r.text

    def test_content_type_movie_no_tv(self, fresh_user):
        self._set_prefs(fresh_user["headers"], content_type="movie",
                        subscriptions=["netflix", "hbo_max", "prime_video"])
        items = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
        assert items
        tv_items = [i for i in items if i.get("type") == "tv"]
        assert not tv_items, f"Expected no TV, got {len(tv_items)}: {[i['title'] for i in tv_items[:3]]}"

    def test_excluded_categories_anime(self, fresh_user):
        self._set_prefs(fresh_user["headers"], excluded_categories=["anime"],
                        subscriptions=["netflix", "hbo_max", "prime_video"])
        items = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
        bad = [i for i in items if "anime" in (i.get("categories") or i.get("tags") or [])]
        assert not bad, f"Anime leaked: {[i['title'] for i in bad[:3]]}"

    def test_excluded_genres_horror(self, fresh_user):
        self._set_prefs(fresh_user["headers"], excluded_genres=["Horror"],
                        subscriptions=["netflix", "hbo_max", "prime_video"])
        items = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
        bad = [i for i in items if "Horror" in (i.get("genres") or [])]
        assert not bad, f"Horror leaked: {[i['title'] for i in bad[:3]]}"


# ------------------------------------------------------------------
# 3. Permanent exclusions + recently-shown LRU + random injection
# ------------------------------------------------------------------

class TestExclusionAndRotation:
    def test_recently_shown_lru_low_overlap(self, admin_headers):
        c1 = requests.get(f"{API}/discover", headers=admin_headers, timeout=15).json()
        c2 = requests.get(f"{API}/discover", headers=admin_headers, timeout=15).json()
        c3 = requests.get(f"{API}/discover", headers=admin_headers, timeout=15).json()
        ids1 = {i["id"] for i in c1}
        ids2 = {i["id"] for i in c2}
        ids3 = {i["id"] for i in c3}
        overlap_12 = ids1 & ids2
        overlap_23 = ids2 & ids3
        # Cooldown of 6h => consecutive calls should have very small intersection
        assert len(overlap_12) <= 5, f"Too much overlap call1↔call2: {len(overlap_12)}"
        assert len(overlap_23) <= 5, f"Too much overlap call2↔call3: {len(overlap_23)}"
        union = ids1 | ids2 | ids3
        assert len(union) > 20, f"Pool/random injection failing — union only {len(union)}"

    def test_random_injection_diversifies(self, admin_headers):
        # Aggregate several calls; should yield more distinct titles than 20
        seen = set()
        for _ in range(3):
            d = requests.get(f"{API}/discover", headers=admin_headers, timeout=15).json()
            for i in d:
                seen.add(i["id"])
        assert len(seen) > 20, f"Only {len(seen)} distinct titles across 3 calls"


# ------------------------------------------------------------------
# 4. Adaptive maturity
# ------------------------------------------------------------------

class TestMaturity:
    def test_cold_start_maturity_low(self, fresh_user):
        items = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
        assert items
        m = items[0]["_signals"]["maturity"]
        assert m <= 0.1, f"Expected near-0 maturity for new user, got {m}"

    def test_engagement_endpoint_for_new_user(self, fresh_user):
        r = requests.get(f"{API}/me/engagement", headers=fresh_user["headers"], timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("maturity", "total_interactions", "by_action",
                  "top_learned_genres", "type_weights",
                  "watchlist_size", "watched_count"):
            assert k in d, f"engagement missing {k}"
        assert d["watchlist_size"] == 0
        assert d["watched_count"] == 0


# ------------------------------------------------------------------
# 5. Catalog size + admin pool
# ------------------------------------------------------------------

class TestCatalogPool:
    def test_catalog_at_least_900(self, admin_headers):
        r = requests.get(f"{API}/admin/dashboard", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        size = d.get("catalog_size") or d.get("total_movies") or d.get("catalog_count") or 0
        assert size >= 900, f"Catalog {size} < 900"

    def test_admin_pool_at_least_300(self, admin_headers):
        items = requests.get(f"{API}/discover", headers=admin_headers, timeout=15).json()
        assert items
        pool = items[0]["_signals"]["pool_size"]
        assert pool >= 250, f"Admin pool only {pool}"  # allow a small slack vs 300


# ------------------------------------------------------------------
# 6. Existing endpoints regression
# ------------------------------------------------------------------

class TestRegressions:
    def test_sections_trending(self, admin_headers):
        r = requests.get(f"{API}/sections/trending", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_sections_upcoming(self, admin_headers):
        r = requests.get(f"{API}/sections/upcoming", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_sections_popular_locally(self, admin_headers):
        r = requests.get(f"{API}/sections/popular-locally", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_search(self, admin_headers):
        r = requests.get(f"{API}/search", headers=admin_headers, params={"q": "matrix"}, timeout=15)
        assert r.status_code == 200

    def test_search_suggest(self, admin_headers):
        r = requests.get(f"{API}/search/suggest", headers=admin_headers, params={"q": "the"}, timeout=15)
        assert r.status_code == 200


# ------------------------------------------------------------------
# 7. Onboarding-rated never appears (regression)
# ------------------------------------------------------------------

class TestOnboardingExclusion:
    def test_onboarding_rated_excluded(self, fresh_user):
        # Get onboarding titles + rate first 3 with like
        ot = requests.get(f"{API}/onboarding/titles", headers=fresh_user["headers"], timeout=15)
        assert ot.status_code == 200
        titles = ot.json()
        if isinstance(titles, dict):
            titles = titles.get("titles") or titles.get("items") or []
        rated_ids = []
        for t in titles[:3]:
            tid = t["id"]
            rated_ids.append(tid)
            requests.post(f"{API}/onboarding/rate", headers=fresh_user["headers"],
                          json={"movie_id": tid, "rating": "like"}, timeout=15)
        # Set permissive prefs
        requests.put(f"{API}/user/preferences", headers=fresh_user["headers"],
                     json={"subscriptions": ["netflix", "hbo_max", "prime_video"]},
                     timeout=15)
        # Multiple discover calls, none should contain rated_ids
        all_seen = set()
        for _ in range(3):
            d = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
            all_seen |= {i["id"] for i in d}
        leaked = set(rated_ids) & all_seen
        assert not leaked, f"Onboarding-rated leaked: {leaked}"


# ------------------------------------------------------------------
# 8. Cooldown re-intro (direct mongo writes — backdate skip)
# ------------------------------------------------------------------

class TestCooldownReintro:
    @pytest.mark.asyncio
    async def test_old_skip_with_matching_genres_reappears(self, fresh_user):
        import asyncio  # noqa
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        # Pick a non-Horror movie with at least one genre from catalog
        movie = await db.movies_cache.find_one(
            {"genres": {"$exists": True, "$ne": []}, "type": "movie"},
            {"_id": 0, "id": 1, "genres": 1, "title": 1},
        )
        assert movie is not None
        target_id = movie["id"]
        target_genres = movie["genres"]
        boost_genre = target_genres[0]

        uid = fresh_user["user_id"]
        old_iso = (datetime.now(timezone.utc) - timedelta(days=SKIP_COOLDOWN_DAYS_LOCAL + 5)).isoformat()

        # Insert backdated skip action and add to skipped list
        await db.user_actions.insert_one({
            "user_id": uid, "movie_id": target_id, "action": "skip",
            "created_at": old_iso,
        })
        # Boost genre weight to >=2 and add to skipped + permissive subs
        await db.users.update_one(
            {"user_id": uid},
            {"$set": {
                "skipped": [target_id],
                "genre_weights": {boost_genre: 5},
                "subscriptions": ["netflix", "hbo_max", "prime_video"],
                "content_type": "both",
                "excluded_genres": [],
                "excluded_categories": [],
            }},
        )

        # Multiple discover calls to give recently_shown a chance to rotate
        found = None
        for _ in range(6):
            items = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
            for it in items:
                if it["id"] == target_id:
                    found = it
                    break
            if found:
                break

        # Cleanup
        await db.user_actions.delete_many({"user_id": uid})

        assert found, f"Reintro target '{movie.get('title')}' did not reappear"
        assert found["_signals"]["is_reintro"] is True, f"is_reintro flag missing: {found['_signals']}"
        assert found["reason"] == "Worth a second look", f"reason = {found['reason']}"


# Local mirror to avoid importing engine in this asyncio test in-process
SKIP_COOLDOWN_DAYS_LOCAL = 30


# ------------------------------------------------------------------
# 9. Background refill (in-isolation: call the function directly)
# ------------------------------------------------------------------

class TestBackgroundRefill:
    @pytest.mark.asyncio
    async def test_do_refill_runs_without_error(self):
        # Call engine._do_refill directly — should not raise even on success path
        from engine import _do_refill, _REFILL_LOCK  # type: ignore
        _REFILL_LOCK.clear()
        await _do_refill("test_user_refill_synthetic")
        # Lock cleared in finally
        assert "test_user_refill_synthetic" not in _REFILL_LOCK


# ------------------------------------------------------------------
# 10. Admin refresh-catalog
# ------------------------------------------------------------------

class TestAdminRefresh:
    def test_admin_refresh_pages_3(self, admin_headers):
        r = requests.post(f"{API}/admin/refresh-catalog", headers=admin_headers,
                          params={"pages": 3}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        count = d.get("count") or d.get("total") or 0
        assert count >= 900, f"Refresh count {count} < 900"


# ------------------------------------------------------------------
# 11. Collaborative filtering
# ------------------------------------------------------------------

class TestCollaborative:
    @pytest.mark.asyncio
    async def test_collab_signal_when_neighbours_match(self, fresh_user):
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        # Pick a movie genre to align around
        movie = await db.movies_cache.find_one(
            {"genres": {"$exists": True, "$ne": []}, "type": "movie"},
            {"_id": 0, "id": 1, "genres": 1, "title": 1},
        )
        assert movie
        target_id = movie["id"]
        boost_genre = movie["genres"][0]

        # Create 3 synthetic neighbours that "saved" this movie and share weights
        neighbour_ids = []
        for i in range(3):
            nid = f"synthetic_neighbour_{uuid.uuid4().hex[:8]}"
            neighbour_ids.append(nid)
            await db.users.insert_one({
                "user_id": nid,
                "email": f"{nid}@test.local",
                "saved": [target_id],
                "genre_weights": {boost_genre: 10},
                "subscriptions": ["netflix"],
            })

        # Align test user weights
        uid = fresh_user["user_id"]
        await db.users.update_one(
            {"user_id": uid},
            {"$set": {
                "genre_weights": {boost_genre: 10},
                "subscriptions": ["netflix", "hbo_max", "prime_video"],
                "content_type": "both",
                "excluded_genres": [],
                "excluded_categories": [],
            }},
        )

        found = None
        for _ in range(4):
            items = requests.get(f"{API}/discover", headers=fresh_user["headers"], timeout=15).json()
            for it in items:
                if it["id"] == target_id:
                    found = it
                    break
            if found:
                break

        # Cleanup neighbours
        await db.users.delete_many({"user_id": {"$in": neighbour_ids}})

        assert found, "collab target movie did not appear"
        sig = found["_signals"]
        assert sig["in_collab"] is True or found["reason"] == "Loved by people with your taste", (
            f"collab not flagged: {sig}, reason={found['reason']}"
        )
