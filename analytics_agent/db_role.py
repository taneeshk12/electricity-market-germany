"""Create / update the agent's read-only PostgreSQL role (the primary security boundary).

The role can:   CONNECT to the warehouse database, USE schema `marts`, SELECT its tables.
The role can't: read `public` (raw facts), write anything, create objects, run long queries.
Session defaults are pinned on the role itself, so they apply to every connection:
read-only transactions, statement timeout, idle-transaction timeout, search_path = marts.

Run with admin credentials: `make agent-role` (reads POSTGRES_* and AGENT_DB_* from .env).
"""

from __future__ import annotations

import logging
import os

from psycopg2 import sql
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)


def apply_agent_role(
    conn: PgConnection,
    *,
    role: str,
    password: str,
    database: str,
    schema: str = "marts",
    tables_owner: str | None = None,
    statement_timeout_ms: int = 5_000,
) -> None:
    """Idempotently create the role and (re)apply its privileges. Caller commits."""
    r, db, sch = sql.Identifier(role), sql.Identifier(database), sql.Identifier(schema)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL(
                "{} ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS "
                "CONNECTION LIMIT 10 PASSWORD {}"
            ).format(sql.SQL(verb), r, sql.Literal(password))
        )
        for setting, value in [
            ("default_transaction_read_only", "on"),
            ("statement_timeout", f"{int(statement_timeout_ms)}ms"),
            ("idle_in_transaction_session_timeout", "30s"),
            ("search_path", schema),
        ]:
            cur.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(r, sql.Identifier(setting), sql.Literal(value)))

        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, r))
        cur.execute(sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM {}").format(db, r))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(r))
        cur.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(r))
        # Since PG 15, PUBLIC has no CREATE on schema public; make sure of it anyway.
        cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sch))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sch, r))
        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(sch, r))
        # dbt recreates mart tables on every build; default privileges re-grant SELECT automatically.
        if tables_owner:
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(
                    sql.Identifier(tables_owner), sch, r
                )
            )
    logger.info(
        "Read-only role %s %s (schema %s, timeout %d ms)",
        role,
        "created" if verb == "CREATE" else "updated",
        schema,
        statement_timeout_ms,
    )


def main() -> None:
    from src import config
    from src.load import get_engine

    config.setup_logging()
    role = os.getenv("AGENT_DB_USER", "emg_agent_ro")
    password = os.getenv("AGENT_DB_PASSWORD")
    if not password:
        raise SystemExit("Set AGENT_DB_PASSWORD in .env first.")
    settings = config.get_db_settings()
    if role == settings.user:
        raise SystemExit("AGENT_DB_USER must differ from POSTGRES_USER.")
    raw = get_engine().raw_connection()
    try:
        apply_agent_role(
            raw,
            role=role,
            password=password,
            database=settings.database,
            tables_owner=settings.user,
            statement_timeout_ms=int(os.getenv("AGENT_STATEMENT_TIMEOUT_MS", "5000")),
        )
        raw.commit()
    finally:
        raw.close()


if __name__ == "__main__":
    main()
