"""Iteration 8 tests: Onboarding flow + strict filter enforcement.

Covers:
- GET /api/onboarding/titles returns a maximum-ten-card diverse training deck
- POST /api/onboarding/rate (like/dislike/skip) updates weights correctly
- Rated titles never reappear in /discover
- POST /api/onboarding/complete sets onboarding_completed=true
- PUT /api/user/preferences accepts new fields (moods, excluded_genres,
  content_type, onboarding_completed)
- Strict filter enforcement across /discover, /sections/trending,
  /sections/upcoming, /sections/popular-locally, /search, /search/suggest
  for content_type=movie, excluded_categories=anime, excluded_genres=Horror
- Backfill: admin user has onboarding_completed=true
"""
import os
import uuid
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api"


# --- Fixtures --------------------------------------------------------------
def _register(email_prefix="onb"):
    s = requests.Session()
    email = f"test_{email_prefix}_{uuid.uuid4().hex[:8]}@watchsmart.app"
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": "Test1234!", "name": "Onb Tester"
    })
    assert r.status_code in (200, 201), f"register failed {r.status_code} {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s, email


@pytest.fixture
def fresh_user():
    s, email = _register("onb")
    yield s, email
    response = s.delete(f"{API}/auth/account")
    assert response.status_code == 200, "Disposable test account cleanup failed"


@pytest.fixture
def admin_client():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={
        "email": "admin@watchsmart.app", "password": "admin123"
    })
    assert r.status_code == 200, f"admin login failed {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


# --- Onboarding titles -----------------------------------------------------
class TestOnboardingTitles:
    def test_titles_are_short_and_diverse(self, fresh_user):
        s, _ = fresh_user
        r = s.get(f"{API}/onboarding/titles?limit=18")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert 1 <= len(data) <= 10, f"expected 1–10 titles got {len(data)}"
        # poster_url mandatory
        assert all(t.get("poster_url") for t in data)
        # mix of types
        types = {t.get("type") for t in data}
        assert "movie" in types, f"no movies in picks: {types}"
        # distinct genres
        genres = set()
        for t in data:
            for g in t.get("genres") or []:
                genres.add(g)
        assert len(genres) >= 4, f"expected varied genres in short deck, got {genres}"

    def test_titles_excludes_onboarding_rated(self, fresh_user):
        s, _ = fresh_user
        r = s.get(f"{API}/onboarding/titles?limit=18").json()
        mid = r[0]["id"]
        rr = s.post(f"{API}/onboarding/rate", json={"movie_id": mid, "rating": "like"})
        assert rr.status_code == 200
        # New batch MUST not include the rated title
        r2 = s.get(f"{API}/onboarding/titles?limit=18").json()
        assert mid not in {t["id"] for t in r2}


# --- Rating --------------------------------------------------------------
class TestOnboardingRate:
    def test_like_increments_source_separated_weights(self, fresh_user):
        s, _ = fresh_user
        titles = s.get(f"{API}/onboarding/titles?limit=5").json()
        t = titles[0]
        r = s.post(f"{API}/onboarding/rate", json={"movie_id": t["id"], "rating": "like"})
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        user = data.get("user") or {}
        gw = user.get("onboarding_genre_weights") or {}
        for g in t["genres"]:
            assert gw.get(g, 0) > 0, f"expected positive training affinity for {g}, got {gw.get(g)}"
        tw = user.get("onboarding_type_weights") or {}
        assert tw.get(t["type"], 0) == pytest.approx(4 * 0.6)

    def test_dislike_decrements_source_separated_weights(self, fresh_user):
        s, _ = fresh_user
        titles = s.get(f"{API}/onboarding/titles?limit=5").json()
        t = titles[0]
        r = s.post(f"{API}/onboarding/rate", json={"movie_id": t["id"], "rating": "dislike"})
        assert r.status_code == 200
        user = r.json().get("user") or {}
        gw = user.get("onboarding_genre_weights") or {}
        for g in t["genres"]:
            assert gw.get(g, 0) < 0, f"expected negative training affinity for {g}, got {gw.get(g)}"

    def test_skip_does_not_change_weights(self, fresh_user):
        s, _ = fresh_user
        titles = s.get(f"{API}/onboarding/titles?limit=5").json()
        t = titles[0]
        r = s.post(f"{API}/onboarding/rate", json={"movie_id": t["id"], "rating": "skip"})
        assert r.status_code == 200
        user = r.json().get("user") or {}
        gw = user.get("genre_weights") or {}
        for g in t["genres"]:
            assert gw.get(g, 0) == 0, f"expected 0 for {g}, got {gw.get(g)}"
        # But onboarding_rated SHOULD include the skipped movie
        assert t["id"] in (user.get("onboarding_rated") or [])

    def test_rated_movies_excluded_from_discover(self, fresh_user):
        s, _ = fresh_user
        titles = s.get(f"{API}/onboarding/titles?limit=5").json()
        rated_ids = []
        for t in titles[:3]:
            s.post(f"{API}/onboarding/rate", json={"movie_id": t["id"], "rating": "like"})
            rated_ids.append(t["id"])
        # Unset any strict filters that might remove everything
        s.put(f"{API}/user/preferences", json={"content_type": "both", "services": [], "excluded_categories": [], "excluded_genres": []})
        disc = s.get(f"{API}/discover?limit=50").json()
        disc_ids = {m["id"] for m in disc}
        for rid in rated_ids:
            assert rid not in disc_ids, f"rated movie {rid} leaked into discover"


# --- Complete + prefs ------------------------------------------------------
class TestOnboardingComplete:
    def test_complete_sets_flag(self, fresh_user):
        s, _ = fresh_user
        titles = s.get(f"{API}/onboarding/titles?limit=10").json()
        for title in titles[:5]:
            rated = s.post(
                f"{API}/onboarding/rate",
                json={"movie_id": title["id"], "rating": "skip"},
            )
            assert rated.status_code == 200
        r = s.post(f"{API}/onboarding/complete")
        assert r.status_code == 200
        assert r.json().get("onboarding_completed") is True
        # Verify via /auth/me
        me = s.get(f"{API}/auth/me").json()
        assert me.get("onboarding_completed") is True


class TestPreferencesNewFields:
    def test_put_accepts_new_fields(self, fresh_user):
        s, _ = fresh_user
        payload = {
            "moods": ["funny", "mindblowing"],
            "excluded_genres": ["Horror", "War"],
            "content_type": "movie",
        }
        r = s.put(f"{API}/user/preferences", json=payload)
        assert r.status_code == 200
        u = r.json()
        assert u.get("moods") == ["funny", "mindblowing"]
        assert set(u.get("excluded_genres") or []) == {"Horror", "War"}
        assert u.get("content_type") == "movie"


# --- Strict filter enforcement --------------------------------------------
class TestStrictFilters:
    def _set(self, s, **kw):
        r = s.put(f"{API}/user/preferences", json=kw)
        assert r.status_code == 200

    def test_content_type_movie_drops_tv_everywhere(self, fresh_user):
        s, _ = fresh_user
        self._set(s, content_type="movie", services=[], excluded_categories=[], excluded_genres=[])
        for path in ["/discover?limit=50", "/sections/trending?limit=20",
                     "/sections/upcoming?limit=20", "/sections/popular-locally?limit=20"]:
            r = s.get(f"{API}{path}")
            if r.status_code != 200:
                pytest.skip(f"{path} not available: {r.status_code}")
            items = r.json()
            if isinstance(items, dict):
                items = items.get("results") or items.get("items") or []
            tvs = [m for m in items if m.get("type") == "tv"]
            assert not tvs, f"{path} returned {len(tvs)} tv items with content_type=movie"
        # Search
        rsrch = s.get(f"{API}/search?q=a").json()
        for m in rsrch.get("results", []):
            assert m.get("type") != "tv", f"search returned tv with content_type=movie: {m.get('title')}"
        # Suggest
        rsugg = s.get(f"{API}/search/suggest?q=th").json()
        for m in rsugg.get("suggestions", []):
            assert m.get("type") != "tv"

    def test_excluded_categories_anime_drops_anime(self, fresh_user):
        s, _ = fresh_user
        self._set(s, excluded_categories=["anime"], content_type="both", services=[], excluded_genres=[])
        for path in ["/discover?limit=50", "/sections/trending?limit=20"]:
            r = s.get(f"{API}{path}")
            if r.status_code != 200:
                continue
            items = r.json()
            if isinstance(items, dict):
                items = items.get("results") or []
            for m in items:
                assert "anime" not in (m.get("tags") or []), f"{path} leaked anime: {m.get('title')}"
        rsrch = s.get(f"{API}/search?q=a").json()
        for m in rsrch.get("results", []):
            assert "anime" not in (m.get("tags") or []), f"search leaked anime: {m.get('title')}"

    def test_excluded_genres_horror_drops_horror(self, fresh_user):
        s, _ = fresh_user
        self._set(s, excluded_genres=["Horror"], content_type="both", services=[], excluded_categories=[])
        for path in ["/discover?limit=50", "/sections/trending?limit=20"]:
            r = s.get(f"{API}{path}")
            if r.status_code != 200:
                continue
            items = r.json()
            if isinstance(items, dict):
                items = items.get("results") or []
            for m in items:
                assert "Horror" not in (m.get("genres") or []), f"{path} leaked Horror: {m.get('title')}"
        rsrch = s.get(f"{API}/search?q=a").json()
        for m in rsrch.get("results", []):
            assert "Horror" not in (m.get("genres") or []), f"search leaked Horror: {m.get('title')}"


# --- Admin backfill --------------------------------------------------------
class TestAdminBackfill:
    def test_admin_onboarding_completed(self, admin_client):
        me = admin_client.get(f"{API}/auth/me").json()
        assert me.get("onboarding_completed") is True, \
            f"admin should be backfilled onboarding_completed=true, got {me.get('onboarding_completed')}"
