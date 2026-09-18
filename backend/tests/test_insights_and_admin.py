"""Backend tests for P0 admin analytics + P1 subscription insights."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@watchsmart.app"
ADMIN_PASSWORD = "admin123"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def fresh_user_token():
    email = f"TEST_insights_{uuid.uuid4().hex[:8]}@watchsmart.app"
    pwd = "Test1234!"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": pwd, "name": "Insights Tester"}, timeout=30)
    assert r.status_code in (200, 201), f"register: {r.status_code} {r.text}"
    # Register typically returns access_token; otherwise login
    data = r.json()
    token = data.get("access_token") or _login(email, pwd)
    # Set subscriptions so insights has data
    r2 = requests.put(
        f"{API}/user/preferences",
        json={"services": ["netflix", "hbo_max", "prime_video"]},
        headers=_auth(token),
        timeout=30,
    )
    assert r2.status_code == 200, f"set services: {r2.status_code} {r2.text}"
    return token


# ---- P0: Admin analytics ----
class TestAdminAnalytics:
    def test_admin_analytics_ok(self, admin_token):
        r = requests.get(f"{API}/admin/analytics", headers=_auth(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for key in ("dau", "wau", "mau", "save_rate_pct", "swipes_7d"):
            assert key in data, f"missing key {key} in {data}"
        assert isinstance(data["swipes_7d"], dict)


# ---- P1: Subscription insights ----
class TestSubscriptionInsights:
    def test_requires_auth(self):
        r = requests.get(f"{API}/insights/subscriptions", timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_admin_insights_shape(self, admin_token):
        r = requests.get(f"{API}/insights/subscriptions?refresh=1", headers=_auth(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # Top-level keys
        for k in ("currency", "month_label", "total_monthly_cost", "total_watched",
                  "services", "unused_services", "potential_savings", "cached_at"):
            assert k in data, f"missing {k}"
        assert data["currency"] == "£"
        assert isinstance(data["services"], list)
        # Per-service keys
        for s in data["services"]:
            for k in ("service_id", "name", "logo_color", "price_monthly",
                      "titles_watched", "cost_per_watch", "tone", "headline",
                      "message", "top_titles"):
                assert k in s, f"missing {k} in service {s}"
            if s["titles_watched"] == 0:
                assert s["cost_per_watch"] is None
                assert s["tone"] == "low"
                assert s["headline"] == "Not used this month"
                assert s["service_id"] in data["unused_services"]

    def test_unused_sorted_first(self, fresh_user_token):
        r = requests.get(f"{API}/insights/subscriptions?refresh=1", headers=_auth(fresh_user_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        svcs = data["services"]
        assert len(svcs) >= 1
        # All unused (titles_watched=0) must appear before any used ones
        seen_used = False
        for s in svcs:
            if s["titles_watched"] > 0:
                seen_used = True
            elif seen_used:
                pytest.fail("Unused service appeared after a used one - sort broken")
        # With zero watched actions, all three should be unused
        assert data["total_watched"] == 0
        assert len(data["unused_services"]) == 3
        assert data["potential_savings"] > 0

    def test_watched_action_invalidates_cache(self, fresh_user_token):
        # Pick a movie available on netflix
        r = requests.get(f"{API}/discover?limit=200", headers=_auth(fresh_user_token), timeout=30)
        assert r.status_code == 200, f"catalog fetch failed: {r.text[:200]}"
        body = r.json()
        catalog = body if isinstance(body, list) else body.get("items", body.get("movies", []))
        target = next((m for m in catalog if "netflix" in (m.get("available_on") or [])), None)
        assert target is not None, "no netflix movie found in catalog"

        # Log watched action
        r2 = requests.post(
            f"{API}/user/action",
            json={"movie_id": target["id"], "action": "watched"},
            headers=_auth(fresh_user_token),
            timeout=30,
        )
        assert r2.status_code == 200, f"user/action: {r2.status_code} {r2.text}"

        # Insights should now reflect it without ?refresh
        r3 = requests.get(f"{API}/insights/subscriptions", headers=_auth(fresh_user_token), timeout=30)
        assert r3.status_code == 200
        data = r3.json()
        netflix = next((s for s in data["services"] if s["service_id"] == "netflix"), None)
        assert netflix is not None
        assert netflix["titles_watched"] >= 1, f"expected netflix titles_watched>=1, got {netflix}"
        assert data["total_watched"] >= 1
        assert netflix["cost_per_watch"] is not None
        assert "netflix" not in data["unused_services"]
