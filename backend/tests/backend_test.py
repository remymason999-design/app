"""WatchSmart backend API tests (iteration 2: affiliate, learning, tutorial support)."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@watchsmart.app"
ADMIN_PASSWORD = "admin123"


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user_ctx():
    email = f"tester_{uuid.uuid4().hex[:8]}@watchsmart.app"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Test1234!", "name": "Tester"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"email": email, "token": data["access_token"], "user": data["user"]}


# --- Auth (cookie + bearer fallback) ---
def test_register_duplicate(user_ctx):
    r = requests.post(f"{API}/auth/register", json={"email": user_ctx["email"], "password": "Test1234!", "name": "x"})
    assert r.status_code == 409


def test_login_invalid():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_login_admin_returns_access_token(admin_token):
    assert admin_token and isinstance(admin_token, str)


def test_me_bearer(user_ctx):
    r = requests.get(f"{API}/auth/me", headers=H(user_ctx["token"]))
    assert r.status_code == 200
    assert r.json()["email"] == user_ctx["email"]


def test_me_cookie():
    """Login via cookie and call /me using cookie only (no bearer)"""
    s = requests.Session()
    email = f"cookieu_{uuid.uuid4().hex[:6]}@watchsmart.app"
    r = s.post(f"{API}/auth/register", json={"email": email, "password": "Test1234!", "name": "CookieU"})
    assert r.status_code == 200
    # Now call me with ONLY cookies
    r2 = s.get(f"{API}/auth/me")
    assert r2.status_code == 200, r2.text
    assert r2.json()["email"] == email


def test_me_unauth():
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401


def test_logout(user_ctx):
    r = requests.post(f"{API}/auth/logout", headers=H(user_ctx["token"]))
    assert r.status_code == 200


# --- Reference data ---
def test_services():
    r = requests.get(f"{API}/services")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all("id" in s and "price_monthly" in s for s in data)


def test_genres():
    r = requests.get(f"{API}/genres")
    assert r.status_code == 200
    assert len(r.json()) >= 5


# --- Preferences + Discover w/ reason field ---
def test_discover_reason_and_filter(user_ctx):
    tok = user_ctx["token"]
    r = requests.put(f"{API}/user/preferences", headers=H(tok),
                     json={"services": ["netflix", "hbo_max"], "genres": ["Sci-Fi", "Drama"]})
    assert r.status_code == 200
    r = requests.get(f"{API}/discover", headers=H(tok))
    assert r.status_code == 200
    movies = r.json()
    assert len(movies) > 0
    for m in movies:
        assert "reason" in m and isinstance(m["reason"], str) and len(m["reason"]) > 0
        assert set(m["available_on"]) & {"netflix", "hbo_max"}


# --- Self-learning genre_weights via $inc ---
def test_genre_weights_inc_on_actions():
    """Save/watched/skip should $inc genre_weights; unsave should NOT."""
    email = f"learn_{uuid.uuid4().hex[:8]}@watchsmart.app"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Test1234!", "name": "L"})
    tok = r.json()["access_token"]

    # Discover 3 movies (no prefs set → all movies pool)
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    assert len(movies) >= 3
    m_save, m_watch, m_skip = movies[0], movies[1], movies[2]

    # save m_save (+2 per genre)
    requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m_save["id"], "action": "save"})
    # watched m_watch (+3 per genre)
    requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m_watch["id"], "action": "watched"})
    # skip m_skip (-1 per genre)
    requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m_skip["id"], "action": "skip"})

    me = requests.get(f"{API}/auth/me", headers=H(tok)).json()
    gw = me.get("genre_weights") or {}
    assert gw, f"genre_weights should be populated, got {gw}"

    # Each genre of m_save should have at least +2 (or +2 -1 if overlap with skip)
    for g in m_save["genres"]:
        assert g in gw
        # +2 from save, potentially -1 if also in skip genres
        expected_min = 2 + (-1 if g in m_skip["genres"] else 0) + (3 if g in m_watch["genres"] else 0)
        assert gw[g] == expected_min, f"genre {g}: got {gw[g]}, expected {expected_min}"

    # Now unsave m_save — should NOT change genre_weights
    before = dict(gw)
    requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": m_save["id"], "action": "unsave"})
    me2 = requests.get(f"{API}/auth/me", headers=H(tok)).json()
    assert (me2.get("genre_weights") or {}) == before, "unsave must not change genre_weights"


def test_discover_reason_reflects_learning():
    """After repeated saves in a genre, reason should mention 'loving <genre>'."""
    email = f"reason_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "R"}).json()["access_token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    # Save top movie
    requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": movies[0]["id"], "action": "save"})
    # Now fetch discover again
    movies2 = requests.get(f"{API}/discover", headers=H(tok)).json()
    assert all("reason" in m for m in movies2)


# --- Affiliate endpoints ---
def test_affiliate_click_and_me(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    m = movies[0]
    svc = m["available_on"][0]
    r = requests.post(f"{API}/affiliate/click", headers=H(tok),
                      json={"movie_id": m["id"], "service_id": svc})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert "utm_source=watchsmart" in url
    assert "utm_medium=referral" in url
    assert "utm_campaign=where-to-watch" in url
    assert f"utm_content={svc}%3A{m['id']}" in url or f"utm_content={svc}:{m['id']}" in url
    assert "ref=watchsmart" in url
    assert "sub_id=" in url

    # /affiliate/me
    r = requests.get(f"{API}/affiliate/me", headers=H(tok))
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(s["service_id"] == svc for s in data["per_service"])


def test_affiliate_click_invalid_service(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    r = requests.post(f"{API}/affiliate/click", headers=H(tok),
                      json={"movie_id": movies[0]["id"], "service_id": "bogus_svc"})
    assert r.status_code == 404


def test_affiliate_stats_admin_only(admin_token, user_ctx):
    # Non-admin blocked
    r = requests.get(f"{API}/affiliate/stats", headers=H(user_ctx["token"]))
    assert r.status_code == 403
    # Admin allowed
    r = requests.get(f"{API}/affiliate/stats", headers=H(admin_token))
    assert r.status_code == 200
    data = r.json()
    assert "total_clicks" in data
    assert "unique_users" in data
    assert "per_service" in data
    if data["per_service"]:
        assert "unique_users" in data["per_service"][0]


def test_affiliate_csv_admin_only(admin_token, user_ctx):
    r = requests.get(f"{API}/affiliate/export.csv", headers=H(user_ctx["token"]))
    assert r.status_code == 403
    r = requests.get(f"{API}/affiliate/export.csv", headers=H(admin_token))
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and "filename=" in cd
    assert "text/csv" in r.headers.get("content-type", "")
    # CSV has header row
    first_line = r.text.split("\n")[0]
    for col in ["created_at", "user_id", "service_id", "movie_id", "tracked_url"]:
        assert col in first_line


# --- Discover excludes seen items ---
def test_discover_excludes_seen():
    email = f"seen_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "S"}).json()["access_token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    m1, m2, m3 = movies[0]["id"], movies[1]["id"], movies[2]["id"]
    for mid, act in [(m1, "save"), (m2, "watched"), (m3, "skip")]:
        requests.post(f"{API}/user/action", headers=H(tok), json={"movie_id": mid, "action": act})
    disc = requests.get(f"{API}/discover", headers=H(tok)).json()
    ids = {m["id"] for m in disc}
    assert m1 not in ids and m2 not in ids and m3 not in ids


def test_movie_not_found(user_ctx):
    r = requests.get(f"{API}/movies/nope", headers=H(user_ctx["token"]))
    assert r.status_code == 404


def test_savings(user_ctx):
    tok = user_ctx["token"]
    requests.put(f"{API}/user/preferences", headers=H(tok),
                 json={"services": ["netflix", "hbo_max", "disney_plus"]})
    r = requests.get(f"{API}/savings", headers=H(tok))
    assert r.status_code == 200
    d = r.json()
    assert d["total_yearly"] == round(d["total_monthly"] * 12, 2)
    assert d["subscription_count"] == 3



# --- Iteration 3: root catalog_size, refresh token, admin dashboard ---
def test_root_catalog_size():
    r = requests.get(f"{API}/")
    assert r.status_code == 200
    data = r.json()
    assert data.get("app") == "WatchSmart"
    assert "catalog_size" in data
    assert isinstance(data["catalog_size"], int)
    assert data["catalog_size"] >= 100, f"catalog too small: {data['catalog_size']}"


def test_catalog_tmdb_size_discover_pool():
    """When no preferences set, discover pool should still return 20 items from 100+ catalog."""
    email = f"pool_{uuid.uuid4().hex[:6]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "P"}).json()["access_token"]
    r = requests.get(f"{API}/discover", headers=H(tok))
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 15, f"discover returned {len(data)} items, expected >=15"
    # Each item must have reason field
    for m in data:
        assert "reason" in m and m["reason"]


def test_auth_refresh_no_token():
    r = requests.post(f"{API}/auth/refresh")
    assert r.status_code == 401


def test_auth_refresh_with_bearer():
    """Login → take refresh token from cookie, then call /auth/refresh with Bearer."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    # refresh_token is httpOnly cookie — use it via session cookies
    refresh = s.cookies.get("refresh_token")
    assert refresh, "refresh_token cookie not set"
    # Call /auth/refresh with Bearer (no cookies)
    r2 = requests.post(f"{API}/auth/refresh", headers={"Authorization": f"Bearer {refresh}"})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert "access_token" in data and len(data["access_token"]) > 20
    # New access token should work for /auth/me
    me = requests.get(f"{API}/auth/me", headers=H(data["access_token"]))
    assert me.status_code == 200


def test_auth_refresh_via_cookie():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    # Call /auth/refresh relying on cookies only
    r2 = s.post(f"{API}/auth/refresh")
    assert r2.status_code == 200
    assert "access_token" in r2.json()


def test_auth_refresh_invalid_token():
    r = requests.post(f"{API}/auth/refresh", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_auth_refresh_rejects_access_token():
    """Access token should NOT work as a refresh token."""
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    access = r.json()["access_token"]
    r2 = requests.post(f"{API}/auth/refresh", headers={"Authorization": f"Bearer {access}"})
    assert r2.status_code == 401


def test_admin_dashboard_rbac(admin_token, user_ctx):
    # Non-admin blocked
    r = requests.get(f"{API}/admin/dashboard", headers=H(user_ctx["token"]))
    assert r.status_code == 403
    # Admin allowed
    r = requests.get(f"{API}/admin/dashboard", headers=H(admin_token))
    assert r.status_code == 200
    data = r.json()
    for key in ["catalog_size", "total_users", "total_clicks", "unique_click_users", "by_service", "recent"]:
        assert key in data, f"missing key {key}"
    assert isinstance(data["catalog_size"], int)
    assert isinstance(data["total_users"], int) and data["total_users"] >= 1
    assert isinstance(data["by_service"], list)
    assert isinstance(data["recent"], list)


def test_admin_refresh_catalog_rbac(user_ctx):
    """Non-admin must get 403 without hitting TMDB."""
    r = requests.post(f"{API}/admin/refresh-catalog", headers=H(user_ctx["token"]))
    assert r.status_code == 403


def test_admin_refresh_catalog_unauth():
    r = requests.post(f"{API}/admin/refresh-catalog")
    assert r.status_code == 401


def test_admin_dashboard_unauth():
    r = requests.get(f"{API}/admin/dashboard")
    assert r.status_code == 401


def test_admin_user_has_role_admin(admin_token):
    r = requests.get(f"{API}/auth/me", headers=H(admin_token))
    assert r.status_code == 200
    assert r.json().get("role") == "admin"
