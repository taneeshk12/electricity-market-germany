"""Tools: validated read-only query execution and data coverage."""

from __future__ import annotations

import logging
from typing import Any

from analytics_agent import config, db
from analytics_agent.sql_validator import validate_sql

logger = logging.getLogger(__name__)

DATE_RANGE_SQL = """
SELECT min(local_date) AS first_local_date, max(local_date) AS last_local_date,
       min(timestamp_utc) AS first_hour_utc, max(timestamp_utc) AS last_hour_utc, count(*) AS hours
FROM marts.fct_market_hourly
"""


def execute_readonly_query(sql: str) -> dict[str, Any]:
    """Validate `sql` and run it as the read-only role. Never raises: errors are returned."""
    cfg = config.get_db_config()
    check = validate_sql(sql, max_rows=cfg.max_rows, max_chars=config.MAX_SQL_CHARS)
    if not check.ok:
        logger.warning("query rejected by validator: %s", "; ".join(check.errors))
        return {"ok": False, "stage": "validation", "error": "; ".join(check.errors), "sql_executed": None}
    try:
        result = db.execute_readonly(check.sql, cfg)
    except db.QueryExecutionError as exc:
        logger.warning("query failed in database: %s", exc)
        return {"ok": False, "stage": "database", "error": str(exc), "sql_executed": check.sql}
    return {
        "ok": True,
        "sql_executed": check.sql,
        "limit_applied": check.limit_applied,
        "tables": check.tables,
        **result.to_dict(),
    }


def get_available_date_range() -> dict[str, Any]:
    """First/last local date and UTC hour available in the warehouse."""
    result = db.execute_readonly(DATE_RANGE_SQL, config.get_db_config())
    return dict(zip(result.columns, result.rows[0], strict=True))
