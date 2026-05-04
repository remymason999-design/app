"""Reelm backend API tests."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://watchsmart-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": "admin@reelm.app", "password": "admin123"})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user_ctx():
    email = f"tester_{uuid.uuid4().hex[:6]}@reelm.app"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Test1234!", "name": "Tester"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"email": email, "token": data["access_token"], "user": data["user"]}


def H(tok): return {"Authorization": f"Bearer {tok}"}


# --- Auth ---
def test_register_duplicate(user_ctx):
    r = requests.post(f"{API}/auth/register", json={"email": user_ctx["email"], "password": "Test1234!", "name": "x"})
    assert r.status_code == 409

def test_login_invalid():
    r = requests.post(f"{API}/auth/login", json={"email": "admin@reelm.app", "password": "wrong"})
    assert r.status_code == 401

def test_login_admin(admin_token):
    assert admin_token

def test_me(user_ctx):
    r = requests.get(f"{API}/auth/me", headers=H(user_ctx["token"]))
    assert r.status_code == 200
    assert r.json()["email"] == user_ctx["email"]

def test_me_unauth():
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401

def test_logout(user_ctx):
    r = requests.post(f"{API}/auth/logout", headers=H(user_ctx["token"]))
    assert r.status_code == 200

def test_google_session_missing_header():
    r = requests.post(f"{API}/auth/google/session")
    assert r.status_code in (401, 422)


# --- Reference ---
def test_services():
    r = requests.get(f"{API}/services")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 8
    assert all("id" in s and "price_monthly" in s for s in data)

def test_genres():
    r = requests.get(f"{API}/genres")
    assert r.status_code == 200
    assert len(r.json()) == 14


# --- Preferences + Discovery ---
def test_preferences_and_discover(user_ctx):
    tok = user_ctx["token"]
    r = requests.put(f"{API}/user/preferences",
                     headers=H(tok),
                     json={"services": ["netflix", "hbo_max"], "genres": ["Sci-Fi", "Drama"]})
    assert r.status_code == 200
    u = r.json()
    assert set(u["subscriptions"]) == {"netflix", "hbo_max"}
    assert set(u["genres"]) == {"Sci-Fi", "Drama"}

    r = requests.get(f"{API}/discover", headers=H(tok))
    assert r.status_code == 200
    movies = r.json()
    assert len(movies) > 0
    # All returned should be available on subscribed services
    for m in movies:
        assert set(m["available_on"]) & {"netflix", "hbo_max"}

def test_movie_detail(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    mid = movies[0]["id"]
    r = requests.get(f"{API}/movies/{mid}", headers=H(tok))
    assert r.status_code == 200
    assert r.json()["id"] == mid

def test_movie_not_found(user_ctx):
    r = requests.get(f"{API}/movies/nope", headers=H(user_ctx["token"]))
    assert r.status_code == 404


# --- Actions & Lists ---
def test_action_save_watched_skip_unsave(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    m1, m2, m3 = movies[0]["id"], movies[1]["id"], movies[2]["id"]

    # save m1
    r = requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m1, "action": "save"})
    assert r.status_code == 200
    assert m1 in r.json()["saved"]

    # watchlist includes m1
    r = requests.get(f"{API}/watchlist", headers=H(tok))
    assert r.status_code == 200
    assert any(x["id"] == m1 for x in r.json())

    # watched m2
    r = requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m2, "action": "watched"})
    assert m2 in r.json()["watched"]
    r = requests.get(f"{API}/watched", headers=H(tok))
    assert any(x["id"] == m2 for x in r.json())

    # skip m3
    r = requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m3, "action": "skip"})
    assert m3 in r.json()["skipped"]

    # re-categorize: save m3 -> should move out of skipped
    r = requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m3, "action": "save"})
    u = r.json()
    assert m3 in u["saved"] and m3 not in u["skipped"]

    # unsave m1
    r = requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m1, "action": "unsave"})
    assert m1 not in r.json()["saved"]

    # discover should exclude seen items
    disc = requests.get(f"{API}/discover", headers=H(tok)).json()
    ids = {m["id"] for m in disc}
    assert m2 not in ids and m3 not in ids


# --- Savings ---
def test_savings(user_ctx):
    tok = user_ctx["token"]
    requests.put(f"{API}/user/preferences", headers=H(tok),
                 json={"services": ["netflix", "hbo_max", "disney_plus"]})
    r = requests.get(f"{API}/savings", headers=H(tok))
    assert r.status_code == 200
    d = r.json()
    assert "total_monthly" in d and "total_yearly" in d
    assert d["total_yearly"] == round(d["total_monthly"] * 12, 2)
    assert d["subscription_count"] == 3
    assert len(d["usage"]) == 3
    assert "overlap_titles" in d
    assert isinstance(d["suggestions"], list)


# --- AI explanation ---
def test_explain(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    mid = movies[0]["id"]
    r = requests.post(f"{API}/recommendations/explain", headers=H(tok),
                      json={"movie_id": mid}, timeout=30)
    assert r.status_code == 200
    assert "explanation" in r.json()
    assert len(r.json()["explanation"]) > 10
