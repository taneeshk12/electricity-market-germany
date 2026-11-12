"""Post-load data quality checks on the PostgreSQL star schema (read-only).

The pre-load checks in quality_checks.py validate the processed parquet files.
These checks validate what actually landed in the warehouse:

* record-count reconciliation between processed files and fact/dimension tables,
* referential integrity (orphans) – FKs enforce this, the check proves it after the fact,
* hourly continuity of dim_datetime and calendar coverage of dim_date,
* NULL keys, value ranges and per-hour source completeness.

Writes docs/warehouse_quality_report.md + .json and exits non-zero on failures.
Only SELECT statements are executed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src import config
from src.quality_checks import FAIL, PASS, WARN, Report, results_table
from src.transform import GENERATION_FILE, PRICE_LOAD_FILE

logger = logging.getLogger(__name__)

REPORT_FILE = config.DOCS_DIR / "warehouse_quality_report.md"
REPORT_JSON = config.DOCS_DIR / "warehouse_quality_report.json"

# (name, description, SQL returning one integer that must be 0)
ZERO_ROW_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("orphans.fact_hourly.timestamp_key", "fact_hourly rows without a dim_datetime row",
     "SELECT count(*) FROM fact_hourly f LEFT JOIN dim_datetime d USING (timestamp_key) "
     "WHERE d.timestamp_key IS NULL"),
    ("orphans.fact_hourly.source_key", "fact_hourly rows without a dim_source row",
     "SELECT count(*) FROM fact_hourly f LEFT JOIN dim_source s USING (source_key) WHERE s.source_key IS NULL"),
    ("orphans.fact_hourly.date_key", "fact_hourly rows without a dim_date row",
     "SELECT count(*) FROM fact_hourly f LEFT JOIN dim_date d USING (date_key) WHERE d.date_key IS NULL"),
    ("orphans.fact_price_load.timestamp_key", "fact_price_load rows without a dim_datetime row",
     "SELECT count(*) FROM fact_price_load f LEFT JOIN dim_datetime d USING (timestamp_key) "
     "WHERE d.timestamp_key IS NULL"),
    ("orphans.dim_datetime.date_key", "dim_datetime rows without a dim_date row",
     "SELECT count(*) FROM dim_datetime t LEFT JOIN dim_date d USING (date_key) WHERE d.date_key IS NULL"),
    ("key_consistency.fact_hourly", "fact_hourly date_key/hour_key agree with dim_datetime",
     "SELECT count(*) FROM fact_hourly f JOIN dim_datetime d USING (timestamp_key) "
     "WHERE f.date_key <> d.date_key OR f.hour_key <> d.hour_key"),
    ("key_consistency.fact_price_load", "fact_price_load date_key/hour_key agree with dim_datetime",
     "SELECT count(*) FROM fact_price_load f JOIN dim_datetime d USING (timestamp_key) "
     "WHERE f.date_key <> d.date_key OR f.hour_key <> d.hour_key"),
    ("hours_without_price_load", "every dim_datetime hour has a fact_price_load row",
     "SELECT count(*) FROM dim_datetime d LEFT JOIN fact_price_load p USING (timestamp_key) "
     "WHERE p.timestamp_key IS NULL"),
    ("hourly_gaps.dim_datetime", "consecutive dim_datetime hours are exactly 1 hour apart",
     "SELECT count(*) FROM (SELECT timestamp_utc - lag(timestamp_utc) OVER (ORDER BY timestamp_utc) AS step "
     "FROM dim_datetime) s WHERE step <> INTERVAL '1 hour'"),
    ("local_dates_missing_in_dim_date", "every local date of the period exists in dim_date",
     "SELECT count(*) FROM generate_series(CAST(:start AS timestamp), CAST(:end AS timestamp), INTERVAL '1 day') g(d) "
     "LEFT JOIN dim_date dd ON dd.date = g.d::date WHERE dd.date_key IS NULL"),
    ("null_price_or_load", "no NULL price or grid load in fact_price_load",
     "SELECT count(*) FROM fact_price_load WHERE price_eur_mwh IS NULL OR consumption_mwh IS NULL"),
)


def _scalar(conn, sql: str, **params) -> int:
    return int(conn.execute(text(sql), params).scalar_one())


def run_checks(engine: Engine, gen: pd.DataFrame, pl: pd.DataFrame) -> Report:
    """Run all warehouse checks against `engine`, reconciling with the processed frames."""
    rep = Report()
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        counts = {t: _scalar(conn, f"SELECT count(*) FROM {t}")  # fixed table names, no user input
                  for t in ("dim_datetime", "fact_price_load", "fact_hourly", "dim_source", "dim_hour")}

        # Record-count reconciliation: rows without a value are intentionally not loaded.
        expected_gen = int(gen["generation_mwh"].notna().sum())
        rep.record("row_count.fact_hourly", "fact_hourly rows = non-null generation rows in the parquet file",
                   expected_gen, counts["fact_hourly"], counts["fact_hourly"] == expected_gen)
        rep.record("row_count.fact_price_load", "fact_price_load rows = rows in the parquet file",
                   len(pl), counts["fact_price_load"], counts["fact_price_load"] == len(pl))
        rep.record("row_count.dim_datetime", "dim_datetime has one row per hour of the period",
                   len(pl), counts["dim_datetime"], counts["dim_datetime"] == len(pl))
        rep.record("row_count.dim_hour", "dim_hour has 24 rows", 24, counts["dim_hour"], counts["dim_hour"] == 24)
        n_sources = int(gen["source"].nunique())
        rep.record("row_count.dim_source", "dim_source covers every pipeline source",
                   f">= {n_sources}", counts["dim_source"], counts["dim_source"] >= n_sources)

        params = {"start": config.START_DATE, "end": config.END_DATE}
        for name, description, sql in ZERO_ROW_CHECKS:
            actual = _scalar(conn, sql, **(params if ":start" in sql else {}))
            rep.record(name, description, 0, actual, actual == 0)

        # Value ranges are enforced by CHECK constraints; verify anyway (cheap, and catches dropped constraints).
        neg = _scalar(conn, "SELECT count(*) FROM fact_hourly WHERE generation_mwh < 0")
        rep.record("range.generation_non_negative", "generation_mwh >= 0", 0, neg, neg == 0)

        # Completeness: hours where fewer sources reported than usual (excluding nuclear after shutdown).
        incomplete = _scalar(conn, """
            SELECT count(*) FROM (
                SELECT f.timestamp_key FROM fact_hourly f JOIN dim_source s USING (source_key)
                WHERE s.source_name <> 'nuclear'
                GROUP BY f.timestamp_key HAVING count(*) < (SELECT count(*) FROM dim_source
                                                             WHERE source_name <> 'nuclear')
            ) x""")
        rep.record("completeness.sources_per_hour", "hours where a non-nuclear source has no value",
                   0, incomplete, incomplete == 0, critical=False,
                   message=f"{incomplete} hours with at least one missing non-nuclear source "
                           "(see data_quality_report.md, section 3)")
    return rep


def write_reports(rep: Report) -> None:
    """Write markdown and JSON reports to docs/."""
    generated = datetime.now(timezone.utc)
    s = {x: sum(r.status == x for r in rep.results) for x in (PASS, WARN, FAIL)}
    md = (
        "# Warehouse quality report\n\n"
        f"Generated: {generated:%Y-%m-%d %H:%M} UTC by `src/warehouse_checks.py` (read-only checks on the "
        f"PostgreSQL star schema after `load`). Period {config.START_DATE} – {config.END_DATE}.\n\n"
        f"**Status: {rep.status}** · {s[PASS]} pass · {s[WARN]} warn · {s[FAIL]} fail\n\n"
        "Machine-readable version: [`warehouse_quality_report.json`](warehouse_quality_report.json).\n\n"
        + results_table(rep.results) + "\n"
    )
    config.DOCS_DIR.mkdir(exist_ok=True)
    REPORT_FILE.write_text(md)
    REPORT_JSON.write_text(json.dumps({
        "generated_at_utc": generated.isoformat(timespec="seconds"),
        "status": rep.status,
        "summary": s,
        "checks": [asdict(r) for r in rep.results],
    }, indent=2) + "\n")


def main() -> None:
    """CLI entry point: check the configured warehouse, exit non-zero on failures."""
    from src.load import get_engine  # local import: keeps this module importable without DB settings

    rep = run_checks(get_engine(), pd.read_parquet(GENERATION_FILE), pd.read_parquet(PRICE_LOAD_FILE))
    write_reports(rep)
    logger.info("Warehouse report written to %s – %s", REPORT_FILE, rep.status)
    if rep.critical:
        raise SystemExit("Warehouse checks failed: " + "; ".join(rep.critical))


if __name__ == "__main__":
    config.setup_logging()
    main()

