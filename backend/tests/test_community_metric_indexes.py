import ast
import asyncio
import os
from pathlib import Path
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


SERVER_PATH = Path(__file__).parents[1] / "server.py"


def _create_index_key_specs() -> list[object]:
    tree = ast.parse(SERVER_PATH.read_text())
    specs = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "create_index"
            and node.value.args
        ):
            continue
        try:
            value = ast.literal_eval(node.value.args[0])
        except (ValueError, TypeError):
            continue
        if isinstance(value, list):
            specs.append(value)
    return specs


def test_community_metric_query_indexes_are_initialized():
    specs = _create_index_key_specs()

    assert [
        ("created_at", 1),
        ("movie_id", 1),
        ("impression_id", 1),
    ] in specs
    assert [
        ("movie_id", 1),
        ("impression_id", 1),
        ("created_at", 1),
    ] in specs
    assert [
        ("at", 1),
        ("impression_id", 1),
        ("items.id", 1),
    ] in specs
    assert [
        ("items.id", 1),
        ("at", 1),
        ("impression_id", 1),
    ] in specs


def _ixscan_names(plan: object) -> list[str]:
    names = []
    if isinstance(plan, dict):
        if plan.get("stage") == "IXSCAN":
            names.append(plan["indexName"])
        for value in plan.values():
            names.extend(_ixscan_names(value))
    elif isinstance(plan, list):
        for value in plan:
            names.extend(_ixscan_names(value))
    return names


def test_incremental_query_indexes_bound_examined_keys():
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        pytest.skip("MongoDB integration environment is not configured")

    async def verify():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        database = client[os.environ["DB_NAME"]]
        suffix = uuid.uuid4().hex
        actions = database[f"_test_metric_actions_{suffix}"]
        impressions = database[f"_test_metric_impressions_{suffix}"]
        try:
            action_index = await actions.create_index(
                [("movie_id", 1), ("impression_id", 1), ("created_at", 1)]
            )
            impression_index = await impressions.create_index(
                [("items.id", 1), ("at", 1), ("impression_id", 1)]
            )
            await actions.insert_many([
                {
                    "movie_id": f"movie-{i % 100}",
                    "impression_id": f"impression-{i}",
                    "created_at": "2026-09-01T00:00:00+00:00",
                }
                for i in range(1000)
            ])
            await impressions.insert_many([
                {
                    "impression_id": f"impression-{i}",
                    "at": "2026-09-01T00:00:00+00:00",
                    "items": [{"id": f"movie-{i % 100}"}],
                }
                for i in range(1000)
            ])

            cases = [
                (
                    actions.name,
                    {
                        "movie_id": "movie-7",
                        "impression_id": {"$in": ["impression-7"]},
                        "created_at": {"$gte": "2026-08-01T00:00:00+00:00"},
                    },
                    action_index,
                ),
                (
                    impressions.name,
                    {
                        "items.id": "movie-7",
                        "at": {"$gte": "2026-08-01T00:00:00+00:00"},
                    },
                    impression_index,
                ),
            ]
            for collection, query, expected_index in cases:
                result = await database.command({
                    "explain": {"find": collection, "filter": query},
                    "verbosity": "executionStats",
                })
                assert expected_index in _ixscan_names(
                    result["queryPlanner"]["winningPlan"]
                )
                assert result["executionStats"]["totalKeysExamined"] <= 10
        finally:
            await actions.drop()
            await impressions.drop()
            client.close()

    asyncio.run(verify())