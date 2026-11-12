"""SQL validator: allowed analytical queries pass; every class of unsafe SQL is rejected."""

from __future__ import annotations

import pytest

from analytics_agent.sql_validator import SqlValidationError, validate_sql

VALID = [
    "SELECT avg(price_eur_mwh) FROM marts.fct_market_hourly WHERE year = 2024",
    "SELECT year_month, renewable_share FROM marts.mart_market_monthly ORDER BY renewable_share DESC LIMIT 5",
    # CTE + window function + join between approved tables
    """WITH m AS (SELECT year, sum(solar_mwh) AS s FROM marts.fct_market_hourly GROUP BY year)
       SELECT year, s, s - lag(s) OVER (ORDER BY year) AS delta FROM m""",
    """SELECT d.local_date, g.source_name, sum(g.generation_mwh)
       FROM marts.mart_market_daily d JOIN marts.fct_generation_hourly g ON g.local_date = d.local_date
       GROUP BY 1, 2""",
    "SELECT corr(residual_load_mwh, price_eur_mwh) FROM marts.fct_market_hourly",
    "SELECT is_weekend, avg(price_eur_mwh) FROM marts.fct_market_hourly GROUP BY is_weekend "
    "UNION ALL SELECT NULL, avg(price_eur_mwh) FROM marts.fct_market_hourly",
    "SELECT count(*) FILTER (WHERE is_negative_price)::numeric / count(*) FROM marts.fct_market_hourly",
    "SELECT * FROM (SELECT year, avg(price_eur_mwh) p FROM marts.fct_market_hourly GROUP BY year) x WHERE p > 50",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price_eur_mwh) FROM marts.fct_market_hourly",
    "SELECT date_trunc('month', timestamp_local), extract(dow FROM local_date) FROM marts.fct_market_hourly",
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_queries_pass(sql: str) -> None:
    result = validate_sql(sql)
    assert result.ok, result.errors
    assert result.sql and result.sql.upper().startswith(("SELECT", "WITH"))


UNSAFE = {
    # writes / DDL / DCL
    "insert": "INSERT INTO marts.fct_market_hourly (year) VALUES (1)",
    "update": "UPDATE marts.fct_market_hourly SET price_eur_mwh = 0",
    "delete": "DELETE FROM marts.fct_market_hourly",
    "merge": "MERGE INTO marts.mart_market_daily d USING marts.mart_market_daily s ON true WHEN MATCHED THEN DELETE",
    "drop": "DROP TABLE marts.fct_market_hourly",
    "alter": "ALTER TABLE marts.fct_market_hourly ADD COLUMN x int",
    "truncate": "TRUNCATE marts.fct_market_hourly",
    "create": "CREATE TABLE marts.x AS SELECT 1",
    "grant": "GRANT ALL ON marts.fct_market_hourly TO public",
    "copy": "COPY marts.fct_market_hourly TO '/tmp/out.csv'",
    "set": "SET statement_timeout = 0",
    "select_into": "SELECT * INTO marts.copy FROM marts.fct_market_hourly",
    "for_update": "SELECT * FROM marts.fct_market_hourly FOR UPDATE",
    "begin": "BEGIN",
    "vacuum": "VACUUM",
    # data-modifying CTE
    "cte_delete": "WITH d AS (DELETE FROM marts.fct_market_hourly RETURNING *) SELECT * FROM d",
    # stacked statements / injection
    "stacked": "SELECT 1 FROM marts.fct_market_hourly; DROP TABLE marts.fct_market_hourly",
    "stacked_comment": "SELECT 1 FROM marts.fct_market_hourly; -- harmless\nDELETE FROM marts.fct_market_hourly",
    # catalogs / other schemas / unknown tables
    "pg_catalog": "SELECT * FROM pg_catalog.pg_authid",
    "pg_tables_unqualified": "SELECT * FROM pg_tables",
    "information_schema": "SELECT * FROM information_schema.columns",
    "public_fact": "SELECT * FROM public.fact_hourly",
    "public_view": "SELECT * FROM v_hourly",
    "unknown_table": "SELECT * FROM marts.secret_table",
    "subquery_catalog": "SELECT (SELECT rolpassword FROM pg_authid LIMIT 1) FROM marts.fct_market_hourly",
    "cross_db": "SELECT * FROM otherdb.marts.fct_market_hourly",
    # dangerous functions
    "pg_sleep": "SELECT pg_sleep(100) FROM marts.fct_market_hourly",
    "pg_read_file": "SELECT pg_read_file('/etc/passwd')",
    "dblink": "SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)",
    "set_config": "SELECT set_config('statement_timeout', '0', false)",
    "current_setting": "SELECT current_setting('data_directory')",
    "lo_import": "SELECT lo_import('/etc/passwd')",
    "generate_series_dos": "SELECT count(*) FROM generate_series(1, 1000000000000)",
    # not SQL
    "empty": "   ",
    "garbage": "SELEC price FROM",
}


@pytest.mark.parametrize("sql", UNSAFE.values(), ids=UNSAFE.keys())
def test_unsafe_queries_are_rejected(sql: str) -> None:
    result = validate_sql(sql)
    assert not result.ok
    assert result.sql is None
    assert result.errors


def test_error_messages_are_specific() -> None:
    assert "exactly one statement" in validate_sql(UNSAFE["stacked"]).errors[0]
    assert any("schema not allowed: pg_catalog" in e for e in validate_sql(UNSAFE["pg_catalog"]).errors)
    assert any("function not allowed: pg_sleep" in e for e in validate_sql(UNSAFE["pg_sleep"]).errors)
    assert any("table not allowed" in e for e in validate_sql(UNSAFE["public_view"]).errors)


def test_length_limit() -> None:
    sql = "SELECT 1 FROM marts.fct_market_hourly WHERE " + " OR ".join(["year = 2024"] * 400)
    assert "longer than" in validate_sql(sql, max_chars=1000).errors[0]


def test_limit_added_when_missing() -> None:
    r = validate_sql("SELECT price_eur_mwh FROM marts.fct_market_hourly", max_rows=100)
    assert r.limit_applied and r.sql.endswith("LIMIT 100")


def test_limit_clamped_when_too_large() -> None:
    r = validate_sql("SELECT price_eur_mwh FROM marts.fct_market_hourly LIMIT 999999", max_rows=100)
    assert r.limit_applied and r.sql.endswith("LIMIT 100") and "999999" not in r.sql


def test_small_limit_kept() -> None:
    r = validate_sql("SELECT price_eur_mwh FROM marts.fct_market_hourly LIMIT 5", max_rows=100)
    assert not r.limit_applied and r.sql.endswith("LIMIT 5")


def test_limit_on_union() -> None:
    r = validate_sql(VALID[5], max_rows=10)
    assert r.ok and r.sql.endswith("LIMIT 10")


def test_unqualified_approved_table_is_qualified() -> None:
    r = validate_sql("SELECT avg(price_eur_mwh) FROM fct_market_hourly")
    assert r.ok and "marts.fct_market_hourly" in r.sql
    assert r.tables == ["marts.fct_market_hourly"]


def test_cte_name_shadowing_is_not_an_escape() -> None:
    # A CTE named like a catalog table is fine (it's the CTE); a schema-qualified catalog is not.
    assert validate_sql("WITH pg_authid AS (SELECT 1 AS x FROM marts.fct_market_hourly) SELECT * FROM pg_authid").ok
    assert not validate_sql("WITH a AS (SELECT 1 x) SELECT * FROM a, pg_catalog.pg_authid").ok


def test_raise_for_errors() -> None:
    with pytest.raises(SqlValidationError, match="forbidden"):
        validate_sql(UNSAFE["delete"]).raise_for_errors()
    assert validate_sql(VALID[0]).raise_for_errors().startswith("SELECT")
