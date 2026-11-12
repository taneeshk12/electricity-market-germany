"""Baseline text-to-SQL: one direct Groq call with a bare schema, executed as-is.

Deliberately minimal, so the comparison isolates what the improved agent adds:
- context: table and column names + types only (no descriptions, metrics, notes or date range)
- no SQL validator, no LIMIT rewrite, no repair attempt
Same model, temperature, token budget and READ-ONLY database role as the improved agent
(the baseline never runs with write privileges; the role is the only safety layer it has).
"""

from __future__ import annotations

import time
from typing import Any

from analytics_agent import config, db, schema_context
from analytics_agent.agent import AgentResult
from analytics_agent.llm import JsonLLM, LLMError

SYSTEM = """You write PostgreSQL queries.
Return ONLY a JSON object {"sql": "<query>"}.
If the question cannot be answered from the tables, return {"sql": null}."""


def bare_schema() -> str:
    return "\n".join(
        f"{t.qualified_name}({', '.join(f'{c.name} {c.type}' for c in t.columns)})" for t in schema_context.TABLES
    )


class BaselineSystem:
    def __init__(self, llm: JsonLLM) -> None:
        self.llm = llm
        self.schema = bare_schema()

    def answer(self, question: str) -> AgentResult:
        result = AgentResult(question=question, status="failed")
        started = time.perf_counter()
        try:
            resp = self.llm.complete_json(SYSTEM, f"Tables:\n{self.schema}\n\nQuestion: {question}")
            result.prompt_tokens, result.completion_tokens = resp.prompt_tokens, resp.completion_tokens
            result.timings_ms["llm_generate"] = resp.latency_ms
            sql = resp.data.get("sql")
            if not sql:
                result.status, result.answer = "abstained", "baseline returned sql=null"
                result.attempts.append({"attempt": 1, "answerable": False})
                return result
            result.sql = str(sql)
            try:
                res = db.execute_readonly(result.sql, config.get_db_config())
            except db.QueryExecutionError as exc:
                result.error = f"database error: {exc}"
                result.attempts.append(
                    {"attempt": 1, "sql": result.sql, "ok": False, "stage": "database", "error": str(exc)}
                )
                return result
            result.attempts.append({"attempt": 1, "sql": result.sql, "ok": True})
            result.status = "answered"
            result.columns, result.rows, result.row_count, result.truncated = (
                res.columns,
                res.rows,
                res.row_count,
                res.truncated,
            )
            return result
        except LLMError as exc:
            result.error = str(exc)
            return result
        finally:
            result.timings_ms["total"] = round((time.perf_counter() - started) * 1000, 1)


def summary(result: AgentResult) -> dict[str, Any]:
    return result.to_dict()
