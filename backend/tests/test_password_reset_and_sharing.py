"""Tests for iteration 7 features: password reset + watchlist sharing."""
import os
import random
import string
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://watchsmart-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _rand(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def alice():
    email = f"test_alice_{_rand()}@watchsmart.app"
    pw = "pass1234"
    name = f"Alice {_rand(3)}"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": name})
    assert r.status_code in (200, 201), r.text
    token = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    # set subscriptions for shared candidates in compare recs
    s.put(f"{API}/user/preferences", json={"subscriptions": ["netflix", "hbo_max", "prime_video"]})
    return {"email": email, "password": pw, "token": token, "session": s, "name": name}


@pytest.fixture(scope="module")
def bob():
    email = f"test_bob_{_rand()}@watchsmart.app"
    pw = "pass1234"
    name = f"Bob {_rand(3)}"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": name})
    assert r.status_code in (200, 201), r.text
    token = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    s.put(f"{API}/user/preferences", json={"subscriptions": ["netflix", "hbo_max", "prime_video"]})
    return {"email": email, "password": pw, "token": token, "session": s, "name": name}


# ---------- password reset ----------

class TestPasswordReset:
    def test_forgot_password_known_email_returns_inline_token(self, alice):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": alice["email"]})
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert body.get("delivery") == "inline"
        assert isinstance(body.get("token"), str) and len(body["token"]) > 10
        assert "reset_url" in body and body["reset_url"].endswith(body["token"])
        assert "expires_at" in body
        alice["_reset_token"] = body["token"]

    def test_forgot_password_unknown_email_no_enumeration(self):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": f"ghost_{_rand()}@nope.tld"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert "token" not in body
        assert "reset_url" not in body

    def test_reset_password_with_bad_token_400(self):
        r = requests.post(f"{API}/auth/reset-password", json={"token": "x" * 40, "new_password": "newpass1"})
        assert r.status_code == 400

    def test_reset_password_happy_path_and_token_reuse_blocked(self, alice):
        token = alice.get("_reset_token")
        assert token, "previous test should have populated token"
        new_pw = "NewPass!234"
        r = requests.post(f"{API}/auth/reset-password", json={"token": token, "new_password": new_pw})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # old password should fail
        r_old = requests.post(f"{API}/auth/login", json={"email": alice["email"], "password": alice["password"]})
        assert r_old.status_code in (400, 401)

        # new password should work
        r_new = requests.post(f"{API}/auth/login", json={"email": alice["email"], "password": new_pw})
        assert r_new.status_code == 200, r_new.text
        new_token = r_new.json().get("access_token") or r_new.json().get("token")
        assert new_token
        # update fixture so subsequent tests use refreshed credentials
        alice["password"] = new_pw
        alice["token"] = new_token
        alice["session"].headers.update({"Authorization": f"Bearer {new_token}"})

        # reuse same token -> 400
        r_reuse = requests.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "another1"})
        assert r_reuse.status_code == 400


# ---------- sharing ----------

class TestSharing:
    def test_share_me_generates_code(self, alice, bob):
        ra = alice["session"].get(f"{API}/share/me")
        assert ra.status_code == 200, ra.text
        a = ra.json()
        assert isinstance(a.get("share_code"), str) and len(a["share_code"]) == 6
        assert a["share_url"].endswith(f"/share/{a['share_code']}")
        assert isinstance(a["watchlist_size"], int)
        alice["share_code"] = a["share_code"]

        rb = bob["session"].get(f"{API}/share/me")
        assert rb.status_code == 200
        b = rb.json()
        assert len(b["share_code"]) == 6
        bob["share_code"] = b["share_code"]

        # idempotent
        ra2 = alice["session"].get(f"{API}/share/me")
        assert ra2.json()["share_code"] == alice["share_code"]

    def test_lookup_self_400_unknown_404_valid_ok(self, alice, bob):
        r_self = alice["session"].post(f"{API}/share/lookup", json={"code": alice["share_code"]})
        assert r_self.status_code == 400

        r_unk = alice["session"].post(f"{API}/share/lookup", json={"code": "ZZZZZZ"})
        assert r_unk.status_code == 404

        r_ok = alice["session"].post(f"{API}/share/lookup", json={"code": bob["share_code"]})
        assert r_ok.status_code == 200
        body = r_ok.json()
        assert body["share_code"] == bob["share_code"]
        assert body["user_id"]
        assert "email" not in body  # privacy

    def test_request_flow_pending_then_accept(self, alice, bob):
        # Alice -> Bob
        r = alice["session"].post(f"{API}/share/request", json={"code": bob["share_code"]})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "sent"

        # Bob sees incoming
        rb = bob["session"].get(f"{API}/share/requests")
        assert rb.status_code == 200
        body = rb.json()
        ids = [x["request_id"] for x in body["incoming"]]
        assert len(ids) >= 1
        req_id = body["incoming"][0]["request_id"]

        # Alice sees outgoing
        ra = alice["session"].get(f"{API}/share/requests")
        out_ids = [x["request_id"] for x in ra.json()["outgoing"]]
        assert req_id in out_ids

        # Bob accepts
        ac = bob["session"].post(f"{API}/share/requests/{req_id}/accept")
        assert ac.status_code == 200, ac.text
        assert ac.json()["status"] == "accepted"

        # Both friends lists include each other
        af = alice["session"].get(f"{API}/share/friends").json()
        bf = bob["session"].get(f"{API}/share/friends").json()
        assert any(f["share_code"] == bob["share_code"] for f in af)
        assert any(f["share_code"] == alice["share_code"] for f in bf)

    def test_compare_classifies_movies(self, alice, bob):
        # discover movies and save: shared_id (both), alice_only, bob_only
        disc = alice["session"].get(f"{API}/discover").json()
        if isinstance(disc, list):
            movies = disc
        elif isinstance(disc, dict):
            movies = disc.get("movies") or disc.get("results") or []
        else:
            movies = []
        assert isinstance(movies, list) and len(movies) >= 3, f"discover returned: {disc}"
        ids = [m["id"] for m in movies[:3]]
        shared, only_a, only_b = ids[0], ids[1], ids[2]

        for mid in (shared, only_a):
            r = alice["session"].post(f"{API}/user/action", json={"movie_id": mid, "action": "save"})
            assert r.status_code in (200, 201), r.text
        for mid in (shared, only_b):
            r = bob["session"].post(f"{API}/user/action", json={"movie_id": mid, "action": "save"})
            assert r.status_code in (200, 201), r.text

        # need bob's user_id from friends list
        af = alice["session"].get(f"{API}/share/friends").json()
        bob_id = next(f["user_id"] for f in af if f["share_code"] == bob["share_code"])
        cmp_resp = alice["session"].get(f"{API}/share/compare/{bob_id}")
        assert cmp_resp.status_code == 200, cmp_resp.text
        c = cmp_resp.json()
        overlap_ids = {m["id"] for m in c["overlap"]}
        only_me_ids = {m["id"] for m in c["only_me"]}
        only_them_ids = {m["id"] for m in c["only_them"]}
        assert shared in overlap_ids
        assert only_a in only_me_ids
        assert only_b in only_them_ids
        assert c["overlap_count"] == len(overlap_ids)
        assert isinstance(c["recommendations"], list)
        # recs exclude saved
        all_seen = {shared, only_a, only_b}
        for rec in c["recommendations"]:
            assert rec["id"] not in all_seen
        assert c["pick_tonight"] is not None
        assert "synced_at" in c

    def test_compare_non_friend_403(self, alice):
        # Register a third user that's not a friend
        email = f"test_carol_{_rand()}@watchsmart.app"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "pass1234", "name": "Carol"})
        carol_token = r.json().get("access_token") or r.json().get("token")
        carol_id = r.json().get("user", {}).get("user_id") or r.json().get("user_id")
        if not carol_id:
            me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {carol_token}"}).json()
            carol_id = me.get("user_id") or me.get("id")
        assert carol_id
        r = alice["session"].get(f"{API}/share/compare/{carol_id}")
        assert r.status_code == 403

    def test_unfriend_removes_both_sides(self, alice, bob):
        af = alice["session"].get(f"{API}/share/friends").json()
        bob_id = next(f["user_id"] for f in af if f["share_code"] == bob["share_code"])
        r = alice["session"].delete(f"{API}/share/friends/{bob_id}")
        assert r.status_code == 200
        af2 = alice["session"].get(f"{API}/share/friends").json()
        bf2 = bob["session"].get(f"{API}/share/friends").json()
        assert not any(f["user_id"] == bob_id for f in af2)
        assert not any(f["share_code"] == alice["share_code"] for f in bf2)


class TestMutualAndReject:
    def test_mutual_auto_accept(self):
        e1 = f"test_m1_{_rand()}@watchsmart.app"
        e2 = f"test_m2_{_rand()}@watchsmart.app"
        r1 = requests.post(f"{API}/auth/register", json={"email": e1, "password": "pass1234", "name": "M1"})
        r2 = requests.post(f"{API}/auth/register", json={"email": e2, "password": "pass1234", "name": "M2"})
        t1 = r1.json().get("access_token") or r1.json().get("token")
        t2 = r2.json().get("access_token") or r2.json().get("token")
        s1 = requests.Session(); s1.headers.update({"Authorization": f"Bearer {t1}"})
        s2 = requests.Session(); s2.headers.update({"Authorization": f"Bearer {t2}"})
        c1 = s1.get(f"{API}/share/me").json()["share_code"]
        c2 = s2.get(f"{API}/share/me").json()["share_code"]
        # 1 -> 2 (pending)
        r = s1.post(f"{API}/share/request", json={"code": c2})
        assert r.json()["status"] == "sent"
        # 2 -> 1 should auto-accept
        r2b = s2.post(f"{API}/share/request", json={"code": c1})
        assert r2b.status_code == 200, r2b.text
        assert r2b.json()["status"] == "accepted"
        # both friends
        f1 = s1.get(f"{API}/share/friends").json()
        f2 = s2.get(f"{API}/share/friends").json()
        assert any(f["share_code"] == c2 for f in f1)
        assert any(f["share_code"] == c1 for f in f2)

    def test_reject_does_not_befriend(self):
        e1 = f"test_r1_{_rand()}@watchsmart.app"
        e2 = f"test_r2_{_rand()}@watchsmart.app"
        r1 = requests.post(f"{API}/auth/register", json={"email": e1, "password": "pass1234", "name": "R1"})
        r2 = requests.post(f"{API}/auth/register", json={"email": e2, "password": "pass1234", "name": "R2"})
        t1 = r1.json().get("access_token") or r1.json().get("token")
        t2 = r2.json().get("access_token") or r2.json().get("token")
        s1 = requests.Session(); s1.headers.update({"Authorization": f"Bearer {t1}"})
        s2 = requests.Session(); s2.headers.update({"Authorization": f"Bearer {t2}"})
        c2 = s2.get(f"{API}/share/me").json()["share_code"]
        s1.get(f"{API}/share/me")
        sent = s1.post(f"{API}/share/request", json={"code": c2}).json()
        assert sent["status"] == "sent"
        req_id = sent["request_id"]
        rj = s2.post(f"{API}/share/requests/{req_id}/reject")
        assert rj.status_code == 200
        assert rj.json()["status"] == "rejected"
        f1 = s1.get(f"{API}/share/friends").json()
        f2 = s2.get(f"{API}/share/friends").json()
        assert f1 == [] or all(f.get("user_id") for f in f1) and not any(f.get("share_code") == c2 for f in f1)
        assert f2 == [] or not any(f for f in f2)
