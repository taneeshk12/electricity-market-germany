"""Deterministic SQL-safety benchmark (no LLM): which layer stops each attack?

Sends known-malicious SQL directly to
  * the improved path: MCP tool logic = SQLGlot validator + read-only role
  * the baseline path: read-only role only (no validator)
and records the outcome. Runs against the real warehouse, which is safe by construction:
nothing reaches the database except as the read-only role. Output: results/safety_results.json

    python -m evaluation.safety_tests
"""

from __future__ import annotations

import json
from pathlib import Path

from analytics_agent import config, db
from analytics_agent.tools.execute_query import execute_readonly_query

OUT = Path(__file__).parent / "results" / "safety_results.json"

ATTACKS: list[tuple[str, str]] = [
    ("delete", "DELETE FROM marts.fct_market_hourly"),
    ("update", "UPDATE marts.fct_market_hourly SET price_eur_mwh = 0"),
    ("insert", "INSERT INTO marts.mart_market_monthly (year_month) VALUES ('2099-01')"),
    ("drop", "DROP TABLE marts.fct_market_hourly"),
    ("truncate", "TRUNCATE marts.mart_market_daily"),
    ("create", "CREATE TABLE marts.pwned AS SELECT 1 AS x"),
    ("alter_role", "ALTER ROLE emg_agent_ro SUPERUSER"),
    ("grant", "GRANT ALL ON ALL TABLES IN SCHEMA public TO PUBLIC"),
    ("stacked", "SELECT 1 FROM marts.fct_market_hourly LIMIT 1; DELETE FROM marts.fct_market_hourly"),
    ("cte_write", "WITH d AS (DELETE FROM marts.fct_market_hourly RETURNING *) SELECT count(*) FROM d"),
    ("select_into", "SELECT * INTO marts.copy_table FROM marts.fct_market_hourly"),
    ("raw_facts", "SELECT count(*) FROM public.fact_hourly"),
    ("password_hashes", "SELECT rolname, rolpassword FROM pg_authid"),
    ("catalog_roles", "SELECT rolname FROM pg_roles"),
    ("information_schema", "SELECT table_schema, table_name FROM information_schema.tables"),
    ("read_file", "SELECT pg_read_file('/etc/passwd')"),
    ("sleep", "SELECT pg_sleep(30)"),
    ("disable_timeout", "SET statement_timeout = 0"),
    ("set_config", "SELECT set_config('default_transaction_read_only', 'off', false)"),
    ("row_lock", "SELECT * FROM marts.fct_market_hourly LIMIT 1 FOR UPDATE"),
]


def baseline_path(sql: str) -> str:
    try:
        res = db.execute_readonly(sql, config.get_db_config())
        return f"EXECUTED ({res.row_count} rows)"
    except db.QueryExecutionError as exc:
        return f"blocked by database: {exc}"


def improved_path(sql: str) -> str:
    res = execute_readonly_query(sql)
    if res["ok"]:
        return f"EXECUTED ({res['row_count']} rows)"
    return f"blocked by {'SQL validator' if res['stage'] == 'validation' else 'database'}: {res['error']}"


def main() -> None:
    rows = []
    for name, sql in ATTACKS:
        rows.append({"attack": name, "sql": sql, "baseline": baseline_path(sql), "improved": improved_path(sql)})
        print(f"{name:20} | baseline: {rows[-1]['baseline'][:60]:60} | improved: {rows[-1]['improved'][:50]}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
