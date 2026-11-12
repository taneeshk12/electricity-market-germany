"""Agent fixtures: a scripted LLM and a fake database behind the real MCP server."""

from __future__ import annotations

from typing import Any

import pytest

from analytics_agent import config, db
from analytics_agent.llm import LLMResponse

FAKE_DB = config.DbConfig(host="x", port=1, database="x", user="ro", password="secret", max_rows=50)


class ScriptedLLM:
    """Returns pre-defined JSON objects in order and records every prompt."""

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> LLMResponse:
        self.calls.append((system, user))
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(data=nxt, prompt_tokens=100, completion_tokens=20, latency_ms=5.0, model="fake")


class FakeDatabase:
    """Records executed SQL; returns canned results or raises a QueryExecutionError."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.fail_with: list[str] = []

    def __call__(self, sql: str, cfg: config.DbConfig, params=None) -> db.QueryResult:
        self.executed.append(sql)
        if "min(local_date)" in sql:
            return db.QueryResult(
                ["first_local_date", "last_local_date", "first_hour_utc", "last_hour_utc", "hours"],
                [["2023-01-01", "2025-12-31", "x", "y", 26304]],
                1,
                False,
                1.0,
            )
        if self.fail_with:
            raise db.QueryExecutionError(self.fail_with.pop(0))
        return db.QueryResult(["year", "avg_price_eur_mwh"], [[2024, 78.51]], 1, False, 2.0)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeDatabase:
    fake = FakeDatabase()
    monkeypatch.setattr(config, "get_db_config", lambda: FAKE_DB)
    monkeypatch.setattr(db, "execute_readonly", fake)
    return fake
