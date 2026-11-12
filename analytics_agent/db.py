"""Execute validated SQL as the read-only agent role and return JSON-friendly results."""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import psycopg2
from psycopg2 import errors as pg_errors

from analytics_agent.config import DbConfig

logger = logging.getLogger(__name__)


class QueryExecutionError(RuntimeError):
    """A query failed in the database (message is safe to show to the user / LLM)."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _json_value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dt.datetime | dt.date | dt.time):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    return v


def connect(cfg: DbConfig):
    """Open a connection as the agent role with read-only, time-limited sessions."""
    return psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.database,
        user=cfg.user,
        password=cfg.password,
        connect_timeout=5,
        application_name="analytics_agent",
        # Also enforced on the role; repeated here so a misconfigured role is still bounded.
        options=f"-c statement_timeout={int(cfg.statement_timeout_ms)} -c default_transaction_read_only=on",
    )


def execute_readonly(sql: str, cfg: DbConfig, params: dict[str, Any] | None = None) -> QueryResult:
    """Run one (already validated) query in a READ ONLY transaction; fetch at most cfg.max_rows rows."""
    started = time.perf_counter()
    conn = connect(cfg)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(sql, params)  # params: only for server-side constants, LLM SQL has none
            columns = [d.name for d in cur.description] if cur.description else []
            fetched = cur.fetchmany(cfg.max_rows + 1)
        conn.rollback()  # nothing to commit; end the transaction explicitly
    except pg_errors.QueryCanceled as exc:
        raise QueryExecutionError(f"query cancelled: exceeded the {cfg.statement_timeout_ms} ms timeout") from exc
    except pg_errors.InsufficientPrivilege as exc:
        raise QueryExecutionError("permission denied: the agent may only read the approved marts tables") from exc
    except pg_errors.ReadOnlySqlTransaction as exc:
        raise QueryExecutionError("write attempted in a read-only transaction") from exc
    except psycopg2.Error as exc:
        # The PostgreSQL message (e.g. 'column "x" does not exist') helps the LLM repair its SQL.
        msg = (exc.pgerror or str(exc)).strip().splitlines()[0]
        raise QueryExecutionError(msg) from exc
    finally:
        conn.close()

    truncated = len(fetched) > cfg.max_rows
    rows = [[_json_value(v) for v in row] for row in fetched[: cfg.max_rows]]
    elapsed = (time.perf_counter() - started) * 1000
    logger.info("query ok: %d rows%s in %.0f ms", len(rows), " (truncated)" if truncated else "", elapsed)
    return QueryResult(columns, rows, len(rows), truncated, round(elapsed, 1))
