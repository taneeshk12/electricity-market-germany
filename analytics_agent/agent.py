"""Question -> SQL -> validated read-only execution -> answer.

Flow (every data access goes through the MCP server's tools):
1. get_database_schema, get_metric_definitions, get_available_date_range  (cached per agent)
2. Groq drafts SQL (or abstains if the question is not answerable from the data)
3. execute_readonly_query validates (SQLGlot) and runs it as the read-only role
4. On a validation or database error, the error is fed back once for a repair attempt
5. Groq explains the result in a few sentences; the SQL and rows are always returned too
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from mcp.client.client import Client

from analytics_agent import config
from analytics_agent.llm import JsonLLM, LLMError
from analytics_agent.sql_generator import (
    build_sql_prompt,
    explain_result,
    format_metrics,
    format_schema,
    generate_sql,
)

logger = logging.getLogger(__name__)

MAX_SQL_ATTEMPTS = 2  # first try + one repair


@dataclass
class AgentResult:
    question: str
    status: str  # answered | abstained | failed
    answer: str = ""
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    limit_applied: bool = False
    assumptions: str = ""
    error: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)  # every SQL tried and what happened
    timings_ms: dict[str, float] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unwrap(exc: BaseException) -> BaseException:
    """Return the first leaf exception of (nested) exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


class AnalyticsAgent:
    def __init__(self, llm: JsonLLM, mcp_target: Any = None, explain: bool = True) -> None:
        if mcp_target is None:
            from analytics_agent.server import server as mcp_target
        self.llm = llm
        self.mcp_target = mcp_target  # MCPServer instance (in-process) or StdioServerParameters / URL
        self.explain = explain
        self._context: tuple[str, str, dict[str, Any] | None] | None = None

    async def _tool(self, client: Client, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        res = await client.call_tool(name, args or {})
        if res.is_error or res.structured_content is None:
            text = res.content[0].text if res.content else "unknown error"
            raise RuntimeError(f"MCP tool {name} failed: {text}")
        return res.structured_content

    async def _load_context(self, client: Client) -> tuple[str, str, dict[str, Any] | None]:
        if self._context is None:
            schema = await self._tool(client, "get_database_schema")
            metrics = await self._tool(client, "get_metric_definitions")
            try:
                date_range = await self._tool(client, "get_available_date_range")
            except RuntimeError as exc:  # coverage is helpful but not essential
                logger.warning("date range unavailable: %s", exc)
                date_range = None
            self._context = (format_schema(schema), format_metrics(metrics["metrics"]), date_range)
        return self._context

    async def answer_async(self, question: str) -> AgentResult:
        question = (question or "").strip()
        result = AgentResult(question=question, status="failed")
        if not question:
            result.error = "Please enter a question."
            return result
        if len(question) > config.MAX_QUESTION_CHARS:
            result.error = f"Question too long (max {config.MAX_QUESTION_CHARS} characters)."
            return result

        total_start = time.perf_counter()
        try:
            async with Client(self.mcp_target, raise_exceptions=False) as client:
                t0 = time.perf_counter()
                schema_text, metrics_text, date_range = await self._load_context(client)
                result.timings_ms["context"] = round((time.perf_counter() - t0) * 1000, 1)

                feedback = None
                for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
                    prompt = build_sql_prompt(question, schema_text, metrics_text, date_range, feedback)
                    draft, resp = await asyncio.to_thread(generate_sql, self.llm, prompt)
                    self._count(result, resp, "generate")
                    result.assumptions = draft.assumptions
                    if not draft.answerable:
                        result.status, result.answer = "abstained", draft.reason or "The data cannot answer this."
                        result.attempts.append({"attempt": attempt, "answerable": False, "reason": draft.reason})
                        return result

                    t0 = time.perf_counter()
                    exec_res = await self._tool(client, "execute_readonly_query", {"sql": draft.sql})
                    result.timings_ms["execute"] = round((time.perf_counter() - t0) * 1000, 1)
                    result.attempts.append(
                        {
                            "attempt": attempt,
                            "sql": draft.sql,
                            "ok": exec_res["ok"],
                            "stage": exec_res.get("stage"),
                            "error": exec_res.get("error"),
                        }
                    )
                    if exec_res["ok"]:
                        break
                    feedback = f"{exec_res['stage']} error: {exec_res['error']}"
                    result.sql, result.error = exec_res.get("sql_executed") or draft.sql, feedback
                else:
                    return result  # all attempts failed; status stays "failed"

            result.status, result.error = "answered", None
            result.sql = exec_res["sql_executed"]
            result.columns, result.rows = exec_res["columns"], exec_res["rows"]
            result.row_count, result.truncated = exec_res["row_count"], exec_res["truncated"]
            result.limit_applied = exec_res.get("limit_applied", False)
            if self.explain:
                try:
                    result.answer, resp = await asyncio.to_thread(
                        explain_result, self.llm, question, result.sql, exec_res
                    )
                    self._count(result, resp, "explain")
                except LLMError as exc:  # the data is still valid; show it without prose
                    result.answer = f"(No explanation: {exc})"
            return result
        except Exception as exc:  # noqa: BLE001 – unwrap anyio exception groups from the MCP client
            inner = _unwrap(exc)
            if not isinstance(inner, RuntimeError):  # LLMError, tool failures; anything else is a bug
                raise
            logger.error("agent failed: %s", inner)
            result.error = str(inner)
            return result
        finally:
            result.timings_ms["total"] = round((time.perf_counter() - total_start) * 1000, 1)
            logger.info(
                "question answered: status=%s attempts=%d total=%.0f ms tokens=%d",
                result.status,
                len(result.attempts),
                result.timings_ms["total"],
                result.prompt_tokens + result.completion_tokens,
            )

    def answer(self, question: str) -> AgentResult:
        """Synchronous wrapper (Streamlit, CLI, evaluation)."""
        return asyncio.run(self.answer_async(question))

    @staticmethod
    def _count(result: AgentResult, resp: Any, step: str) -> None:
        result.prompt_tokens += resp.prompt_tokens
        result.completion_tokens += resp.completion_tokens
        result.timings_ms[f"llm_{step}"] = round(result.timings_ms.get(f"llm_{step}", 0) + resp.latency_ms, 1)
