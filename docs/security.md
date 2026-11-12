# Security design: natural-language analytics agent

**Threat model.** SQL written by an LLM is untrusted input. A user, or text injected through a question,
may try to make the model read data it should not see, write or delete data, exhaust the database, or reveal
credentials. Prompt instructions are **not** treated as a control. Every control below works even if the model
fully ignores its instructions.

## Layers (outermost first)

| # | Layer | Enforced by | What it stops |
|---|---|---|---|
| 1 | Input limits | `agent.py` | empty or oversized questions (`AGENT_MAX_QUESTION_CHARS`, 500) |
| 2 | SQL validation | `sql_validator.py` (SQLGlot AST) | anything other than **one** SELECT/UNION query; DML/DDL/DCL, `COPY`, `SET`, `SELECT INTO`, `FOR UPDATE`, transaction control, data-modifying CTEs; any table outside the 4 approved `marts` tables (so no `pg_catalog`, `information_schema` or `public`); dangerous functions (`pg_*`, `dblink`, `lo_*`, `set_config`, `current_setting`, `generate_series`, …); SQL over 4,000 chars |
| 3 | Row limit | validator rewrites the outer `LIMIT` to ≤ `AGENT_MAX_ROWS`; the executor fetches at most max+1 rows | huge result sets |
| 4 | **Database role (primary boundary)** | `db_role.py` → role `emg_agent_ro` | see below |
| 5 | Session limits | role settings and connection options | long-running queries (`statement_timeout` 5 s), idle transactions (30 s) |
| 6 | Secrets hygiene | `config.py`, `llm.py` | the API key and DB passwords are excluded from reprs, never logged, never sent to the model; the agent refuses to run as the admin user |

### The read-only role

```
LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 10
ALTER ROLE … SET default_transaction_read_only = on, statement_timeout = 5000ms,
                 idle_in_transaction_session_timeout = 30s, search_path = marts
GRANT CONNECT ON DATABASE; REVOKE CREATE, TEMPORARY ON DATABASE
REVOKE ALL ON SCHEMA public (+ all its tables)
GRANT USAGE ON SCHEMA marts; GRANT SELECT ON ALL TABLES IN SCHEMA marts
ALTER DEFAULT PRIVILEGES … IN SCHEMA marts GRANT SELECT ON TABLES   -- survives dbt rebuilds
```

Because the role has only `SELECT` on `marts`, writes fail on **privileges** even if read-only mode were turned
off. `tests/integration/test_agent_role.py` proves this with a multi-statement string that first runs
`SET TRANSACTION READ WRITE`. Every test in that file bypasses the validator and talks to PostgreSQL directly.

## Verification

| Evidence | Where |
|---|---|
| 54 validator tests: 10 valid analytical queries, 35 unsafe inputs (DML, DDL, stacked statements, comment tricks, catalogs, `public`, cross-database, `pg_sleep`, `pg_read_file`, `dblink`, `lo_import`, `set_config`, row locks, `SELECT INTO`, data-modifying CTE, …), plus limit and qualification rules | `tests/unit/agent/test_sql_validator.py` |
| Database refuses writes, `public`, catalogs, temp tables and file reads; timeout fires; grants survive table recreation | `tests/integration/test_agent_role.py` |
| Unsafe SQL from the LLM is never executed; it is sent back for repair | `tests/unit/agent/test_agent.py` |
| Live check against the warehouse | `make agent-check` |

## Parameterisation

LLM-generated SQL is a complete query with literal values, so there are no user parameters to bind. That is why it
is parsed and checked as a whole and runs under a least-privilege role. The executor accepts bind parameters
(`execute_readonly(sql, cfg, params)`) for server-side queries.

## Known limits

- The validator blocks functions with a denylist. A harmless but unexpected function may pass, so the role,
  the timeout and the row limit remain the real boundary.
- `pg_catalog` is readable by every PostgreSQL role (a PostgreSQL design). The validator blocks it, but the role alone does not.
- Local Docker exposes PostgreSQL on port 5433 with password auth. Do not expose it publicly (see Week 4 deployment).
- Question text goes to Groq (a third-party API). Database credentials and query results beyond the first 30 rows do not.
