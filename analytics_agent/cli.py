"""Command line entry points.

python -m analytics_agent.cli "What was the average price in 2024?"
python -m analytics_agent.cli --models            # list models available to your Groq key
python -m analytics_agent.cli --check             # schema context + role permissions vs. live DB
python -m analytics_agent.cli --verify-metrics    # run every metric example -> docs/metric_catalogue.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from analytics_agent import config, db, metrics, schema_context
from analytics_agent.sql_validator import validate_sql
from src import config as pipeline_config
from src.reporting import df_to_markdown

CATALOGUE_MD = pipeline_config.DOCS_DIR / "metric_catalogue.md"


def check() -> int:
    """Verify the curated schema against information_schema and the role's actual privileges."""
    cfg = config.get_db_config()
    cols = db.execute_readonly(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'marts'", cfg
    )
    by_table: dict[str, set[str]] = {}
    for t, c in cols.rows:
        by_table.setdefault(t, set()).add(c)
    problems = schema_context.verify_against_database(by_table)
    for probe, sql in [
        ("public schema must be unreadable", "SELECT 1 FROM public.fact_hourly LIMIT 1"),
        ("writes must fail", "CREATE TABLE marts.should_not_exist (x int)"),
    ]:
        try:
            db.execute_readonly(sql, cfg)
            problems.append(f"SECURITY: {probe}, but the statement succeeded")
        except db.QueryExecutionError as exc:
            print(f"ok   {probe}: {exc}")
    for p in problems:
        print(f"FAIL {p}")
    print("schema context and role permissions OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def verify_metrics() -> int:
    """Execute each metric's example SQL as the agent role and document the actual results."""
    import pandas as pd

    cfg = config.get_db_config()
    out = [
        f"# Metric catalogue\n\nGenerated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by "
        "`python -m analytics_agent.cli --verify-metrics`. Each example query was validated by the SQL "
        f"validator and executed as the read-only role `{cfg.user}`; results below are real.\n"
        "Source of truth: [`analytics_agent/metrics.py`](../analytics_agent/metrics.py).\n"
    ]
    failures = 0
    for m in metrics.METRICS:
        check = validate_sql(m.example_sql, max_rows=cfg.max_rows)
        try:
            res = db.execute_readonly(check.raise_for_errors(), cfg)
            table = df_to_markdown(pd.DataFrame(res.rows, columns=res.columns), index=False)
        except Exception as exc:  # report, keep going
            failures += 1
            table = f"**FAILED:** {exc}"
        out.append(
            f"## {m.name}\n\n{m.definition}\n\n| | |\n|---|---|\n| Formula | `{m.formula}` |\n"
            f"| Tables | {', '.join(f'`{t}`' for t in m.tables)} |\n"
            f"| Columns | {', '.join(f'`{c}`' for c in m.columns)} |\n"
            f"| Aggregation | {m.aggregation} |\n| Unit | {m.unit} |\n| Limitations | {m.limitations} |\n\n"
            f"Example: *{m.example_question}*\n\n```sql\n{m.example_sql}\n```\n\n{table}\n"
        )
    CATALOGUE_MD.write_text("\n".join(out))
    print(f"wrote {CATALOGUE_MD} ({len(metrics.METRICS)} metrics, {failures} failed)")
    return 1 if failures else 0


def list_models() -> int:
    import groq

    client = groq.Groq(api_key=_key())
    for m in sorted(client.models.list().data, key=lambda m: m.id):
        print(m.id)
    return 0


def _key() -> str:
    import os

    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise config.ConfigError("GROQ_API_KEY is not set")
    return key


def ask(question: str, as_json: bool) -> int:
    from analytics_agent.agent import AnalyticsAgent
    from analytics_agent.llm import GroqLLM

    result = AnalyticsAgent(GroqLLM(config.get_llm_config())).answer(question)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"[{result.status}] {result.answer or result.error}\n\nSQL:\n{result.sql}\n")
        print(" | ".join(result.columns))
        for row in result.rows[:20]:
            print(" | ".join(str(v) for v in row))
        print(
            f"\n{result.row_count} rows · {result.timings_ms.get('total')} ms · "
            f"{result.prompt_tokens}+{result.completion_tokens} tokens"
        )
    return 0 if result.status != "failed" else 1


def main() -> None:
    pipeline_config.setup_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-metrics", action="store_true")
    args = parser.parse_args()
    try:
        if args.models:
            sys.exit(list_models())
        if args.check:
            sys.exit(check())
        if args.verify_metrics:
            sys.exit(verify_metrics())
        if not args.question:
            parser.error("ask a question or use --models / --check / --verify-metrics")
        sys.exit(ask(args.question, args.json))
    except config.ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")


if __name__ == "__main__":
    main()
