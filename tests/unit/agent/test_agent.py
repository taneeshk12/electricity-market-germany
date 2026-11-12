"""Agent orchestration through the real MCP server, with a scripted LLM and a fake database."""

from __future__ import annotations

from analytics_agent.agent import AnalyticsAgent
from analytics_agent.llm import LLMError, LLMOutputError
from tests.unit.agent.conftest import ScriptedLLM

GOOD_SQL = "SELECT year, avg(price_eur_mwh) AS avg_price_eur_mwh FROM marts.fct_market_hourly GROUP BY year"


def test_answers_question_end_to_end(fake_db) -> None:
    llm = ScriptedLLM(
        {"answerable": True, "sql": GOOD_SQL, "assumptions": "calendar year"},
        {"answer": "The average price in 2024 was 78.51 EUR/MWh."},
    )
    r = AnalyticsAgent(llm).answer("What was the average price in 2024?")
    assert r.status == "answered"
    assert r.rows == [[2024, 78.51]] and r.columns == ["year", "avg_price_eur_mwh"]
    assert r.sql.startswith("SELECT") and r.sql.endswith("LIMIT 50")  # validator applied the row limit
    assert r.answer.startswith("The average price")
    assert r.assumptions == "calendar year"
    assert r.prompt_tokens == 200 and r.completion_tokens == 40
    assert {"total", "execute", "llm_generate", "llm_explain"} <= set(r.timings_ms)
    # The prompt was grounded in what the MCP tools returned.
    prompt = llm.calls[0][1]
    assert "marts.fct_market_hourly" in prompt and "renewable_share" in prompt and "2025-12-31" in prompt
    assert "What was the average price in 2024?" in prompt


def test_abstains_when_data_cannot_answer(fake_db) -> None:
    llm = ScriptedLLM({"answerable": False, "sql": None, "reason": "Gas prices are not in the dataset."})
    r = AnalyticsAgent(llm).answer("What was the gas price in 2024?")
    assert r.status == "abstained" and "Gas prices" in r.answer
    assert r.sql is None
    assert not [s for s in fake_db.executed if "min(local_date)" not in s]  # nothing else executed


def test_unsafe_sql_is_never_executed_and_repair_is_attempted(fake_db) -> None:
    llm = ScriptedLLM(
        {"answerable": True, "sql": "DELETE FROM marts.fct_market_hourly"},
        {"answerable": True, "sql": GOOD_SQL},
        {"answer": "ok"},
    )
    r = AnalyticsAgent(llm).answer("Average price per year?")
    assert r.status == "answered"
    assert len(r.attempts) == 2 and r.attempts[0]["stage"] == "validation"
    assert not any("DELETE" in s for s in fake_db.executed)
    assert "YOUR PREVIOUS SQL FAILED" in llm.calls[1][1] and "forbidden operation" in llm.calls[1][1]


def test_database_error_feeds_back_once_then_fails(fake_db) -> None:
    fake_db.fail_with = ['column "pricee" does not exist', 'column "pricee" does not exist']
    bad = "SELECT avg(pricee) FROM marts.fct_market_hourly"
    llm = ScriptedLLM({"answerable": True, "sql": bad}, {"answerable": True, "sql": bad})
    r = AnalyticsAgent(llm).answer("Average price?")
    assert r.status == "failed"
    assert len(r.attempts) == 2
    assert 'column "pricee" does not exist' in r.error
    assert 'database error: column "pricee"' in llm.calls[1][1]


def test_invalid_llm_output_is_reported(fake_db) -> None:
    r = AnalyticsAgent(ScriptedLLM(LLMOutputError("model did not return valid JSON"))).answer("Average price?")
    assert r.status == "failed" and "valid JSON" in r.error


def test_wrong_json_shape_is_reported(fake_db) -> None:
    r = AnalyticsAgent(ScriptedLLM({"answerable": True})).answer("Average price?")  # no sql
    assert r.status == "failed" and "wrong shape" in r.error


def test_explanation_failure_still_returns_data(fake_db) -> None:
    llm = ScriptedLLM({"answerable": True, "sql": GOOD_SQL}, LLMError("Groq unavailable"))
    r = AnalyticsAgent(llm).answer("Average price?")
    assert r.status == "answered" and r.rows and "No explanation" in r.answer


def test_input_limits(fake_db) -> None:
    agent = AnalyticsAgent(ScriptedLLM())
    assert agent.answer("   ").status == "failed"
    assert "too long" in agent.answer("x" * 10_000).error


def test_database_unreachable_is_reported(fake_db, monkeypatch) -> None:
    from analytics_agent import db

    def down(*a, **k):
        raise db.QueryExecutionError("could not connect")

    monkeypatch.setattr(db, "execute_readonly", down)
    llm = ScriptedLLM({"answerable": True, "sql": GOOD_SQL}, {"answerable": True, "sql": GOOD_SQL})
    r = AnalyticsAgent(llm).answer("Average price?")
    assert r.status == "failed" and "could not connect" in r.error
