"""Schema context and metric catalogue are consistent with each other and with the validator."""

from __future__ import annotations

import pytest

from analytics_agent import metrics, schema_context
from analytics_agent.sql_validator import validate_sql


@pytest.mark.parametrize("metric", metrics.METRICS, ids=lambda m: m.name)
def test_metric_examples_pass_validator(metric) -> None:
    assert validate_sql(metric.example_sql).ok


@pytest.mark.parametrize("metric", metrics.METRICS, ids=lambda m: m.name)
def test_metric_references_exist_in_schema_context(metric) -> None:
    all_columns = {c.name for t in schema_context.TABLES for c in t.columns}
    for table in metric.tables:
        assert table.split(".")[1] in schema_context.APPROVED_TABLES
    for col in metric.columns:
        assert col in all_columns, col


def test_metric_documentation_complete() -> None:
    for m in metrics.METRICS:
        assert all([m.definition, m.formula, m.unit, m.limitations, m.aggregation, m.example_question])


def test_verify_against_database_detects_drift() -> None:
    actual = {t.name: {c.name for c in t.columns} for t in schema_context.TABLES}
    assert schema_context.verify_against_database(actual) == []
    actual["fct_market_hourly"].discard("price_eur_mwh")
    del actual["mart_market_daily"]
    problems = schema_context.verify_against_database(actual)
    assert len(problems) == 2 and any("price_eur_mwh" in p for p in problems)
