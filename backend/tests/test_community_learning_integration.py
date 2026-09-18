"""End-to-end coverage for the community-learning recommendation pipeline."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import db, mongo_client  # noqa: E402

_configured_backend = os.environ.get("REACT_APP_BACKEND_URL", "")
BASE_URL = (
    _configured_backend.rstrip("/")
    if _configured_backend.startswith(("http://", "https://"))
    else "http://localhost:8000"
)
API = f"{BASE_URL}/api"


async def _wait_for(collection, query: dict, timeout: float = 5.0) -> dict | None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if doc := await collection.find_one(query):
            return doc
        await asyncio.sleep(0.1)
    return None


async def _new_context() -> dict:
    run_id = uuid.uuid4().hex
    email = f"community-{run_id}@example.com"
    password = "CommunityTest123!"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{API}/auth/register",
            json={"email": email, "password": password, "name": "Community Pipeline Test"},
        )
        assert response.status_code in (200, 201), response.text
        token = response.json().get("access_token")
        if not token:
            login = await client.post(
                f"{API}/auth/login", json={"email": email, "password": password}
            )
            assert login.status_code == 200, login.text
            token = login.json()["access_token"]
    user = await db.users.find_one({"email": email})
    assert user, "registered integration-test user was not persisted"
    return {
        "token": token,
        "user_id": user["user_id"],
        "user_ids": {user["user_id"]},
        "impression_ids": set(),
        "movie_ids": set(),
        "prior_metrics": {},
    }


async def _cleanup(context: dict) -> None:
    user_ids = list(context["user_ids"])
    await db.users.delete_many({"user_id": {"$in": user_ids}})
    await db.user_actions.delete_many({"user_id": {"$in": user_ids}})
    if context["impression_ids"]:
        await db.impressions.delete_many(
            {"impression_id": {"$in": list(context["impression_ids"])}}
        )
    if context["movie_ids"]:
        for movie_id in context["movie_ids"]:
            prior = context["prior_metrics"].get(movie_id)
            if prior:
                await db.title_metrics.replace_one({"movie_id": movie_id}, prior, upsert=True)
            else:
                await db.title_metrics.delete_one({"movie_id": movie_id})


async def _feed_action_scenario() -> None:
    context = await _new_context()
    try:
        headers = {"Authorization": f"Bearer {context['token']}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{API}/discover?limit=10", headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            cards = body if isinstance(body, list) else body.get("items", body.get("movies", []))
            assert cards, "discover returned no cards"
            assert all(card.get("impression_id") for card in cards)
            feed_ids = {card["impression_id"] for card in cards}
            assert len(feed_ids) == 1, "one feed must share one impression_id"

            impression_id = feed_ids.pop()
            context["impression_ids"].add(impression_id)
            target = cards[0]
            movie_id = target["id"]
            context["movie_ids"].add(movie_id)
            context["prior_metrics"][movie_id] = await db.title_metrics.find_one(
                {"movie_id": movie_id}
            )
            generated = await _wait_for(
                db.impressions,
                {"user_id": context["user_id"], "impression_id": impression_id},
            )
            assert generated, "generated feed impression was not persisted"
            assert movie_id in {item.get("id") for item in generated.get("items", [])}

            # Community metrics are intentionally gated until 20 impressions.
            now = datetime.now(timezone.utc).isoformat()
            supplemental = []
            for index in range(19):
                iid = f"community-{uuid.uuid4()}"
                context["impression_ids"].add(iid)
                supplemental.append({
                    "user_id": f"community-history-{index}",
                    "impression_id": iid,
                    "at": now,
                    "count": 1,
                    "items": [{
                        "id": movie_id, "title": target.get("title"), "rank": 0,
                        "slot": "core", "served_at": now, "feed_size": 1,
                    }],
                })
            await db.impressions.insert_many(supplemental)
            action = await client.post(
                f"{API}/user/action",
                headers=headers,
                json={"movie_id": movie_id, "action": "save", "impression_id": impression_id},
            )
            assert action.status_code == 200, action.text

        action_doc = await _wait_for(
            db.user_actions,
            {"user_id": context["user_id"], "movie_id": movie_id, "action": "save"},
        )
        assert action_doc and action_doc.get("impression_id") == impression_id
        metric = await _wait_for(db.title_metrics, {"movie_id": movie_id})
        assert metric, "incremental title metric did not update within five seconds"
        assert metric["impressions"] >= 20
        assert metric["saves"] >= 1
    finally:
        await _cleanup(context)


def test_feed_action_updates_linked_community_metric():
    mongo_client._io_loop = None
    asyncio.run(_feed_action_scenario())


class _AsyncRows:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        self._iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class _MetricCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, *_args, **_kwargs):
        return _AsyncRows(self.rows)


class _ClusterCollection:
    async def find_one(self, query, *_args, **_kwargs):
        if query.get("cluster_id") == "crime_thriller_prestige":
            return {"top_titles": [{"movie_id": "community-winner"}]}
        return None


async def _community_ranking_scenario() -> None:
    from global_learning import compute_new_user_boost

    isolated_db = type("IsolatedDB", (), {
        "title_metrics": _MetricCollection([
            {
                "movie_id": "baseline-winner",
                "title_success_score": 0.1,
                "confidence": 1.0,
            },
            {
                "movie_id": "community-winner",
                "title_success_score": 0.8,
                "confidence": 1.0,
            },
        ]),
        "taste_clusters": _ClusterCollection(),
    })()
    catalog = [{"id": "baseline-winner"}, {"id": "community-winner"}]
    new_user = {
        "saved": [], "watched": [], "skipped": [], "onboarding_rated": [],
        "genre_weights": {"Crime": 4.0, "Thriller": 3.0, "Mystery": 2.0},
    }
    boosts = await compute_new_user_boost(new_user, catalog, isolated_db)
    base_scores = {"baseline-winner": 1.0, "community-winner": 0.0}
    ranked = sorted(
        catalog,
        key=lambda movie: base_scores[movie["id"]] + boosts.get(movie["id"], 0),
        reverse=True,
    )
    assert ranked[0]["id"] == "community-winner"
    assert boosts["community-winner"] > 1.6  # includes the cluster top-title nudge

    mature_user = {**new_user, "saved": [f"seen-{index}" for index in range(20)]}
    assert await compute_new_user_boost(mature_user, catalog, isolated_db) == {}


def test_day_one_community_and_cluster_signals_change_ranking():
    asyncio.run(_community_ranking_scenario())


async def _admin_recompute_scenario(monkeypatch) -> None:
    import global_learning
    from routers import admin
    from server import app

    async def fake_metrics():
        return {"status": "ok", "computed": 2, "impressions_processed": 40}

    async def fake_clusters():
        return {
            "status": "ok",
            "clusters": {"crime_thriller_prestige": 2},
            "total_users": 2,
        }

    monkeypatch.setattr(global_learning, "compute_title_metrics", fake_metrics)
    monkeypatch.setattr(global_learning, "build_taste_clusters", fake_clusters)
    app.dependency_overrides[admin.require_admin] = lambda: {
        "user_id": "isolated-admin", "role": "admin"
    }
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/recompute-metrics",
            )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["metrics"]["status"] == "ok"
        assert result["metrics"]["computed"] > 0
        assert result["clusters"]["status"] == "ok"
        assert result["clusters"]["total_users"] > 0
        assert any(count > 0 for count in result["clusters"]["clusters"].values())
    finally:
        app.dependency_overrides.pop(admin.require_admin, None)


def test_admin_recompute_returns_non_empty_metrics_and_clusters(monkeypatch):
    mongo_client._io_loop = None
    asyncio.run(_admin_recompute_scenario(monkeypatch))