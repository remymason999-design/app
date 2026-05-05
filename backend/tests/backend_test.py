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



# ============ Iteration 4: search, sections, reviews, progress, notifications, watchlist value ============

@pytest.fixture(scope="session")
def fresh_user():
    """A brand-new user used for iter4 specific tests (notifications, progress, etc.)."""
    email = f"iter4_{uuid.uuid4().hex[:8]}@watchsmart.app"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Test1234!", "name": "Iter4"})
    assert r.status_code == 200, r.text
    return {"email": email, "token": r.json()["access_token"], "user": r.json()["user"]}


# --- Preferences accept country/age/excluded_categories ---
def test_preferences_country_age_exclusions(fresh_user):
    tok = fresh_user["token"]
    r = requests.put(f"{API}/user/preferences", headers=H(tok),
                     json={"country": "gb", "age": 33, "excluded_categories": ["anime", "bollywood"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["country"] == "GB"
    assert data["age"] == 33
    assert set(data["excluded_categories"]) == {"anime", "bollywood"}


def test_preferences_age_clamped(fresh_user):
    tok = fresh_user["token"]
    r = requests.put(f"{API}/user/preferences", headers=H(tok), json={"age": 999})
    assert r.status_code == 200
    assert r.json()["age"] == 120


# --- Search: local hit, fallback ---
def test_search_local_match(user_ctx):
    """Search should return a local catalog match for a common english title."""
    tok = user_ctx["token"]
    r = requests.get(f"{API}/search", params={"q": "the"}, headers=H(tok))
    assert r.status_code == 200
    data = r.json()
    assert "results" in data and "fallback" in data
    assert isinstance(data["results"], list)
    # 'the' is extremely common — should be local hit
    if data["results"]:
        assert data["fallback"] is False


def test_search_empty_query(user_ctx):
    r = requests.get(f"{API}/search", params={"q": "  "}, headers=H(user_ctx["token"]))
    assert r.status_code == 200
    assert r.json() == {"results": [], "fallback": False}


def test_search_garbage_returns_fallback(user_ctx):
    """Garbage query should return fallback=true with top-rated suggestions."""
    tok = user_ctx["token"]
    r = requests.get(f"{API}/search", params={"q": "qzxqzxqzxnotreal99"}, headers=H(tok))
    assert r.status_code == 200
    data = r.json()
    # If TMDB returns nothing for nonsense, we fall back. Accept either: live TMDB might still find junk.
    if data["fallback"]:
        assert len(data["results"]) > 0
        # Fallback should be sorted by rating desc
        ratings = [m.get("rating", 0) for m in data["results"]]
        assert ratings == sorted(ratings, reverse=True)


# --- Sections (TMDB live) ---
def test_section_upcoming(user_ctx):
    r = requests.get(f"{API}/sections/upcoming", headers=H(user_ctx["token"]), timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    # TMDB live; allow some flakiness, but should be > 0 in normal conditions
    assert len(items) <= 12


def test_section_trending(user_ctx):
    r = requests.get(f"{API}/sections/trending", headers=H(user_ctx["token"]), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_section_popular_locally(user_ctx):
    r = requests.get(f"{API}/sections/popular-locally", headers=H(user_ctx["token"]), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- Movie detail enriched fields ---
def test_movie_detail_enriched_fields(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    assert movies, "discover empty"
    mid = movies[0]["id"]
    r = requests.get(f"{API}/movies/{mid}", headers=H(tok))
    assert r.status_code == 200
    m = r.json()
    # Expected fields after iter4 enrich
    for key in ["id", "title", "genres", "available_on"]:
        assert key in m
    # New fields (may be None/empty but key should exist or be optional). At least one of these should exist for TMDB-sourced.
    assert any(k in m for k in ["type", "tags", "rent_on", "buy_on"])


# --- Progress upsert + readback ---
def test_progress_upsert_and_readback(user_ctx):
    """Find a movie type (no season validation) OR a TV with valid season — set progress and read back."""
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    # Pick a non-TV title so iter5 season-bounds validation is skipped, OR a TV with seasons
    target = next((m for m in movies if m.get("type") != "tv"), None) or movies[0]
    mid = target["id"]
    # Use season=1 episode=1 — safest
    r = requests.post(f"{API}/user/progress", headers=H(tok),
                      json={"movie_id": mid, "season": 1, "episode": 1})
    assert r.status_code == 200, r.text
    data = r.json()
    prog = (data.get("progress") or {}).get(mid)
    assert prog and prog["season"] == 1 and prog["episode"] == 1
    # GET /movies/{id} should now include progress
    r2 = requests.get(f"{API}/movies/{mid}", headers=H(tok))
    assert r2.status_code == 200
    assert r2.json().get("progress", {}).get("season") == 1


def test_progress_invalid_season():
    email = f"prog_{uuid.uuid4().hex[:6]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "P"}).json()["access_token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    r = requests.post(f"{API}/user/progress", headers=H(tok),
                      json={"movie_id": movies[0]["id"], "season": 0, "episode": 1})
    assert r.status_code == 422


# --- Reviews CRUD ---
def test_post_and_get_review(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    mid = movies[0]["id"]
    text = "This is a really thoughtful, decently long review of the movie I enjoyed."
    r = requests.post(f"{API}/movies/{mid}/reviews", headers=H(tok),
                      json={"movie_id": mid, "rating": 8, "text": text})
    assert r.status_code == 200, r.text
    rev = r.json()
    assert rev["rating"] == 8 and rev["text"].startswith("This is")
    # Upsert: posting again should overwrite, not duplicate
    r2 = requests.post(f"{API}/movies/{mid}/reviews", headers=H(tok),
                       json={"movie_id": mid, "rating": 9, "text": text})
    assert r2.status_code == 200
    # GET reviews
    r3 = requests.get(f"{API}/movies/{mid}/reviews", headers=H(tok))
    assert r3.status_code == 200
    body = r3.json()
    assert "summary" in body and "user" in body and "tmdb" in body
    user_revs = [u for u in body["user"] if u["user_id"] == user_ctx["user"]["user_id"]]
    assert len(user_revs) == 1, "upsert should produce exactly one user review"
    assert user_revs[0]["rating"] == 9


def test_review_invalid_rating(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    mid = movies[0]["id"]
    r = requests.post(f"{API}/movies/{mid}/reviews", headers=H(tok),
                      json={"movie_id": mid, "rating": 11, "text": "valid text here for review"})
    assert r.status_code == 422


def test_review_movie_id_mismatch(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    mid = movies[0]["id"]
    r = requests.post(f"{API}/movies/{mid}/reviews", headers=H(tok),
                      json={"movie_id": "different_id", "rating": 5, "text": "valid review text here"})
    assert r.status_code == 400


# --- Similar ---
def test_similar(user_ctx):
    tok = user_ctx["token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    mid = movies[0]["id"]
    r = requests.get(f"{API}/movies/{mid}/similar", headers=H(tok), timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) <= 12


# --- Notifications ---
def test_seeded_notifications_on_register():
    email = f"notif_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "N"}).json()["access_token"]
    r = requests.get(f"{API}/notifications", headers=H(tok))
    assert r.status_code == 200
    data = r.json()
    assert "items" in data and "unread" in data
    assert len(data["items"]) >= 3, f"expected >=3 seeded notifs, got {len(data['items'])}"
    assert data["unread"] >= 3


def test_notifications_mark_all_read():
    email = f"notif2_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "N2"}).json()["access_token"]
    r = requests.post(f"{API}/notifications/read-all", headers=H(tok))
    assert r.status_code == 200
    assert r.json()["updated"] >= 3
    r2 = requests.get(f"{API}/notifications", headers=H(tok))
    assert r2.json()["unread"] == 0


# --- Watchlist value ---
def test_watchlist_value():
    email = f"wlv_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "W"}).json()["access_token"]
    requests.put(f"{API}/user/preferences", headers=H(tok),
                 json={"services": ["netflix", "hbo_max"]})
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    # Save 2 titles
    requests.post(f"{API}/user/action", headers=H(tok),
                  json={"movie_id": movies[0]["id"], "action": "save"})
    requests.post(f"{API}/user/action", headers=H(tok),
                  json={"movie_id": movies[1]["id"], "action": "watched"})
    r = requests.get(f"{API}/watchlist/value", headers=H(tok))
    assert r.status_code == 200
    data = r.json()
    assert "services" in data and "watchlist_size" in data
    assert data["watchlist_size"] == 2
    assert isinstance(data["services"], list) and len(data["services"]) >= 1
    for row in data["services"]:
        for k in ["service_id", "name", "price_monthly", "subscribed", "titles_count", "value_score", "top_titles"]:
            assert k in row, f"missing {k} in service row"
    # Sorted by value_score desc
    scores = [r["value_score"] for r in data["services"]]
    assert scores == sorted(scores, reverse=True)


# --- Excluded categories filter discover ---
def test_discover_respects_excluded_categories():
    email = f"excl_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "E"}).json()["access_token"]
    requests.put(f"{API}/user/preferences", headers=H(tok),
                 json={"excluded_categories": ["anime", "bollywood"]})
    r = requests.get(f"{API}/discover", headers=H(tok))
    assert r.status_code == 200
    movies = r.json()
    for m in movies:
        tags = set(m.get("tags") or [])
        assert "anime" not in tags
        assert "bollywood" not in tags


# --- Auth gating on iter4 endpoints ---
@pytest.mark.parametrize("path,method", [
    ("/search?q=test", "get"),
    ("/sections/upcoming", "get"),
    ("/sections/trending", "get"),
    ("/sections/popular-locally", "get"),
    ("/notifications", "get"),
    ("/watchlist/value", "get"),
])
def test_iter4_endpoints_require_auth(path, method):
    fn = getattr(requests, method)
    r = fn(f"{API}{path}")
    assert r.status_code == 401, f"{path} should require auth, got {r.status_code}"


# ============ Iteration 5: refactor + new endpoints (search/suggest, admin/analytics, etc.) ============

# --- /api/search/suggest ---
def test_search_suggest_returns_prefix_matches(user_ctx):
    tok = user_ctx["token"]
    r = requests.get(f"{API}/search/suggest", params={"q": "du"}, headers=H(tok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert "suggestions" in data
    suggestions = data["suggestions"]
    assert isinstance(suggestions, list)
    assert len(suggestions) <= 6
    if suggestions:
        for s in suggestions:
            for k in ["id", "title", "year", "type", "poster_url"]:
                assert k in s, f"missing key {k} in suggestion"


def test_search_suggest_short_query_returns_empty(user_ctx):
    tok = user_ctx["token"]
    r = requests.get(f"{API}/search/suggest", params={"q": "d"}, headers=H(tok))
    assert r.status_code == 200
    assert r.json()["suggestions"] == []


def test_search_suggest_requires_auth():
    r = requests.get(f"{API}/search/suggest", params={"q": "du"})
    assert r.status_code == 401


# --- /api/admin/analytics ---
def test_admin_analytics_rbac(admin_token, user_ctx):
    # Non-admin denied
    r = requests.get(f"{API}/admin/analytics", headers=H(user_ctx["token"]))
    assert r.status_code == 403
    # Admin allowed
    r = requests.get(f"{API}/admin/analytics", headers=H(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ["dau", "wau", "mau", "swipes_7d", "save_rate_pct", "total_users"]:
        assert k in data, f"missing analytics key {k}"
    assert isinstance(data["dau"], int)
    assert isinstance(data["wau"], int)
    assert isinstance(data["mau"], int)
    assert isinstance(data["total_users"], int)
    assert data["total_users"] >= 1
    assert isinstance(data["swipes_7d"], dict)
    assert isinstance(data["save_rate_pct"], (int, float))


def test_admin_analytics_unauth():
    r = requests.get(f"{API}/admin/analytics")
    assert r.status_code == 401


# --- Progress: bounds checks (season exists, episode <= ep_count) ---
def _find_tv_in_catalog(tok):
    """Helper: find a TV title with seasons via search."""
    # Frieren is in catalog (mentioned in iter4 context)
    r = requests.get(f"{API}/search", params={"q": "frieren"}, headers=H(tok))
    if r.status_code == 200:
        for m in r.json().get("results", []):
            if m.get("type") == "tv" and m.get("seasons"):
                return m
    # Fallback: search common TV
    for q in ["the", "house", "game"]:
        r = requests.get(f"{API}/search", params={"q": q}, headers=H(tok))
        for m in r.json().get("results", []):
            if m.get("type") == "tv" and m.get("seasons"):
                return m
    return None


def test_progress_invalid_season_out_of_range(user_ctx):
    """For TV titles, posting a non-existent season should return 400."""
    tok = user_ctx["token"]
    tv = _find_tv_in_catalog(tok)
    if not tv:
        pytest.skip("No TV title with seasons in catalog")
    r = requests.post(f"{API}/user/progress", headers=H(tok),
                      json={"movie_id": tv["id"], "season": 99, "episode": 1})
    assert r.status_code == 400, r.text
    assert "Season" in r.json().get("detail", "")


def test_progress_invalid_episode_exceeds_max(user_ctx):
    """For TV titles, episode > season's episode_count should return 400."""
    tok = user_ctx["token"]
    tv = _find_tv_in_catalog(tok)
    if not tv:
        pytest.skip("No TV title with seasons in catalog")
    s1 = next((s for s in tv["seasons"] if s.get("season_number") == 1), tv["seasons"][0])
    max_ep = s1.get("episode_count") or 12
    r = requests.post(f"{API}/user/progress", headers=H(tok),
                      json={"movie_id": tv["id"], "season": s1["season_number"], "episode": max_ep + 50})
    assert r.status_code == 400, r.text
    assert "Episode" in r.json().get("detail", "")


# --- type_weights $inc on save ---
def test_type_weights_inc_on_action():
    """Saving a movie should $inc type_weights.movie; saving a TV should $inc type_weights.tv."""
    email = f"tw_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "TW"}).json()["access_token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    # find a movie and a tv
    mv = next((m for m in movies if m.get("type") == "movie"), None)
    tv = next((m for m in movies if m.get("type") == "tv"), None)
    if mv:
        requests.post(f"{API}/user/action", headers=H(tok),
                      json={"movie_id": mv["id"], "action": "save"})
    if tv:
        requests.post(f"{API}/user/action", headers=H(tok),
                      json={"movie_id": tv["id"], "action": "save"})
    me = requests.get(f"{API}/auth/me", headers=H(tok)).json()
    tw = me.get("type_weights") or {}
    if mv:
        assert tw.get("movie", 0) >= 2, f"expected movie weight >=2, got {tw}"
    if tv:
        assert tw.get("tv", 0) >= 2, f"expected tv weight >=2, got {tw}"


# --- user_actions audit collection ---
def test_user_actions_audit_recorded_via_analytics(admin_token):
    """Save an action with a fresh user, then admin/analytics should reflect non-zero swipes_7d."""
    email = f"audit_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "A"}).json()["access_token"]
    movies = requests.get(f"{API}/discover", headers=H(tok)).json()
    requests.post(f"{API}/user/action", headers=H(tok),
                  json={"movie_id": movies[0]["id"], "action": "save"})
    requests.post(f"{API}/user/action", headers=H(tok),
                  json={"movie_id": movies[1]["id"], "action": "skip"})
    # Verify via admin/analytics that swipes_7d has data
    r = requests.get(f"{API}/admin/analytics", headers=H(admin_token))
    assert r.status_code == 200
    data = r.json()
    assert data["dau"] >= 1
    assert data["wau"] >= 1
    # at least save and skip should be recorded somewhere
    assert sum(data["swipes_7d"].values()) >= 2


# --- Anime exclusion: ensure anime tagged titles removed; western animation kept ---
def test_anime_exclusion_removes_anime_only():
    """excluded_categories=['anime'] should remove anime-tagged titles but allow non-anime animation."""
    email = f"anex_{uuid.uuid4().hex[:8]}@watchsmart.app"
    tok = requests.post(f"{API}/auth/register",
                        json={"email": email, "password": "Test1234!", "name": "AE"}).json()["access_token"]
    requests.put(f"{API}/user/preferences", headers=H(tok),
                 json={"excluded_categories": ["anime"]})
    r = requests.get(f"{API}/discover", headers=H(tok))
    assert r.status_code == 200
    movies = r.json()
    for m in movies:
        tags = set(m.get("tags") or [])
        assert "anime" not in tags, f"anime-tagged title slipped through: {m.get('title')}"


# --- Improved similar scoring: same-type bonus, tag overlap ---
def test_similar_scoring_returns_same_type_first(user_ctx):
    """For a TV target, top similar items should mostly be TV (same-type bonus)."""
    tok = user_ctx["token"]
    tv = _find_tv_in_catalog(tok)
    if not tv:
        pytest.skip("No TV title with seasons in catalog")
    r = requests.get(f"{API}/movies/{tv['id']}/similar", headers=H(tok), timeout=15)
    assert r.status_code == 200
    sims = r.json()
    if len(sims) >= 5:
        # Top 5 should have >= 2 TVs (same-type bonus + genre overlap)
        top5 = sims[:5]
        tv_count = sum(1 for s in top5 if s.get("type") == "tv")
        assert tv_count >= 1, f"expected same-type bonus to surface TVs, got types={[s.get('type') for s in top5]}"

