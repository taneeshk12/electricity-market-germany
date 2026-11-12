"""The read-only role is the primary security boundary – tested WITHOUT the SQL validator.

Each test talks to PostgreSQL directly as the agent role, so these guarantees hold even if
validation were bypassed or buggy.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from analytics_agent import config, db
from analytics_agent.db_role import apply_agent_role


@pytest.fixture
def agent_cfg(clean_db: Engine):
    url = clean_db.url
    role, password = f"emg_test_agent_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    with clean_db.begin() as conn:
        conn.execute(text("CREATE SCHEMA marts"))
        conn.execute(text("CREATE TABLE marts.fct_market_hourly (year int, price_eur_mwh numeric)"))
        conn.execute(text("INSERT INTO marts.fct_market_hourly VALUES (2024, 78.51), (2024, -5)"))
        conn.execute(text("CREATE TABLE public.fact_hourly (x int)"))
    raw = clean_db.raw_connection()
    try:
        apply_agent_role(
            raw,
            role=role,
            password=password,
            database=url.database,
            tables_owner=url.username,
            statement_timeout_ms=500,
        )
        apply_agent_role(
            raw,
            role=role,
            password=password,
            database=url.database,
            tables_owner=url.username,
            statement_timeout_ms=500,
        )  # idempotent
        raw.commit()
    finally:
        raw.close()
    cfg = config.DbConfig(
        host=url.host,
        port=url.port,
        database=url.database,
        user=role,
        password=password,
        statement_timeout_ms=500,
        max_rows=1,
    )
    yield cfg
    with clean_db.begin() as conn:
        conn.execute(text(f'DROP OWNED BY "{role}"'))
    with clean_db.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))


def test_can_read_marts(agent_cfg) -> None:
    res = db.execute_readonly("SELECT year, price_eur_mwh FROM fct_market_hourly ORDER BY price_eur_mwh", agent_cfg)
    assert res.rows == [[2024, -5.0]]  # search_path = marts; Decimal -> float
    assert res.truncated is True  # max_rows=1 of 2


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM public.fact_hourly",
        "INSERT INTO marts.fct_market_hourly VALUES (1, 1)",
        "UPDATE marts.fct_market_hourly SET price_eur_mwh = 0",
        "DELETE FROM marts.fct_market_hourly",
        "CREATE TABLE marts.x (y int)",
        "CREATE TEMP TABLE x (y int)",
        "DROP TABLE marts.fct_market_hourly",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT * FROM pg_authid",
    ],
)
def test_writes_and_sensitive_reads_are_refused_by_database(agent_cfg, sql) -> None:
    with pytest.raises(db.QueryExecutionError):
        db.execute_readonly(sql, agent_cfg)


def test_privileges_hold_even_if_read_only_mode_is_switched_off(agent_cfg) -> None:
    # Multi-statement string (the validator would reject it) that disables read-only mode first.
    sql = "SET TRANSACTION READ WRITE; INSERT INTO marts.fct_market_hourly VALUES (1, 1)"
    with pytest.raises(db.QueryExecutionError):
        db.execute_readonly(sql, agent_cfg)


def test_statement_timeout(agent_cfg) -> None:
    with pytest.raises(db.QueryExecutionError, match="timeout"):
        db.execute_readonly("SELECT pg_sleep(3)", agent_cfg)


def test_tables_recreated_later_are_readable(agent_cfg, clean_db: Engine) -> None:
    # dbt drops and recreates mart tables; default privileges must re-grant SELECT.
    with clean_db.begin() as conn:
        conn.execute(text("DROP TABLE marts.fct_market_hourly"))
        conn.execute(text("CREATE TABLE marts.fct_market_hourly AS SELECT 2025 AS year, 1.0 AS price_eur_mwh"))
    assert db.execute_readonly("SELECT year FROM marts.fct_market_hourly", agent_cfg).rows == [[2025]]


def test_role_attributes(agent_cfg, clean_db: Engine) -> None:
    with clean_db.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolconfig FROM pg_roles WHERE rolname = :r"),
            {"r": agent_cfg.user},
        ).one()
    assert not row.rolsuper and not row.rolcreatedb and not row.rolcreaterole and not row.rolinherit
    assert "default_transaction_read_only=on" in row.rolconfig
