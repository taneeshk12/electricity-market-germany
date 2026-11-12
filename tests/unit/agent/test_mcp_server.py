"""MCP server: tool surface, annotations, and validation before any database access."""

from __future__ import annotations

import asyncio

from mcp.client.client import Client

from analytics_agent.server import server


def _run(coro):
    return asyncio.run(coro)


async def _list():
    async with Client(server) as c:
        return (await c.list_tools()).tools


async def _call(name, args=None):
    async with Client(server) as c:
        return await c.call_tool(name, args or {})


def test_exposes_exactly_the_four_read_only_tools() -> None:
    tools = _run(_list())
    assert {t.name for t in tools} == {
        "get_database_schema",
        "get_metric_definitions",
        "execute_readonly_query",
        "get_available_date_range",
    }
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False
        assert t.description


def test_schema_tool_returns_only_marts() -> None:
    res = _run(_call("get_database_schema")).structured_content
    names = [t["name"] for t in res["tables"]]
    assert names and all(n.startswith("marts.") for n in names)
    assert not any("fact_hourly" == n.split(".")[1] for n in names)


def test_metric_tool() -> None:
    res = _run(_call("get_metric_definitions")).structured_content
    assert {"renewable_share", "negative_price_hours", "average_day_ahead_price"} <= {m["name"] for m in res["metrics"]}


def test_execute_rejects_unsafe_sql_before_touching_db(fake_db) -> None:
    res = _run(_call("execute_readonly_query", {"sql": "DROP TABLE marts.fct_market_hourly"})).structured_content
    assert res["ok"] is False and res["stage"] == "validation"
    assert fake_db.executed == []


def test_execute_runs_validated_sql(fake_db) -> None:
    res = _run(
        _call("execute_readonly_query", {"sql": "SELECT avg(price_eur_mwh) FROM fct_market_hourly"})
    ).structured_content
    assert res["ok"] is True and res["rows"] == [[2024, 78.51]]
    assert fake_db.executed == [res["sql_executed"]]
    assert "marts.fct_market_hourly" in res["sql_executed"] and "LIMIT 50" in res["sql_executed"]


def test_date_range(fake_db) -> None:
    res = _run(_call("get_available_date_range")).structured_content
    assert res["first_local_date"] == "2023-01-01" and res["hours"] == 26304
