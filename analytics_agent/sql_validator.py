"""Validate LLM-generated SQL before it reaches the database.

This is defence in depth. The *primary* boundary is the database: the agent connects as a
role that can only SELECT from schema `marts`, in read-only transactions with a statement
timeout (scripts/create_agent_role.py). This validator rejects everything else early and
with a clear message, using an allowlist approach:

* exactly one statement, which must be a query (SELECT / UNION / INTERSECT / EXCEPT, CTEs ok)
* no write, DDL, DCL, transaction-control, COPY, SET, SELECT INTO or row-locking clauses anywhere
* every table reference is a CTE defined in the query or an approved table in schema `marts`
  (system catalogs, information_schema and `public` are therefore impossible)
* no functions that can sleep, read files, open connections or change settings
* a LIMIT no larger than the configured maximum is enforced (added if missing)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from analytics_agent.schema_context import APPROVED_SCHEMA, APPROVED_TABLES

QUERY_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Revoke,
    exp.Set,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
    exp.Lock,
    exp.Use,
    exp.Pragma,
    exp.LoadData,
    exp.Comment,
    exp.Describe,
    exp.Kill,
)

# Functions that could sleep, touch files/network, inspect/alter server state, or generate huge data.
FORBIDDEN_FUNCTION_PREFIXES: tuple[str, ...] = ("pg_", "dblink", "lo_", "txid_", "xml", "query_to_", "table_to_")
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "current_setting",
        "set_config",
        "version",
        "current_user",
        "session_user",
        "user",
        "inet_server_addr",
        "inet_client_addr",
        "has_table_privilege",
        "has_schema_privilege",
        "copy",
        "generate_series",
        "repeat",
        "lpad",
        "rpad",
        "row_to_json",
        "to_regclass",
        "nextval",
        "setval",
        "currval",
    }
)


class SqlValidationError(ValueError):
    """Raised (or reported) when SQL is not allowed."""


@dataclass
class ValidationResult:
    ok: bool
    sql: str | None = None  # normalised SQL that may be executed (LIMIT enforced, tables qualified)
    errors: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    limit_applied: bool = False

    def raise_for_errors(self) -> str:
        if not self.ok:
            raise SqlValidationError("; ".join(self.errors))
        assert self.sql is not None
        return self.sql


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def _limit_value(query: exp.Expression) -> int | None:
    limit = query.args.get("limit")
    if limit is None:
        return None
    value = limit.expression if isinstance(limit, exp.Limit) else limit
    if isinstance(value, exp.Literal) and value.is_int:
        return int(value.this)
    return -1  # non-literal limit (expression / parameter) -> replace


def validate_sql(sql: str, *, max_rows: int = 500, max_chars: int = 4_000) -> ValidationResult:
    """Check `sql` against the policy above; never raises for bad input, returns errors instead."""
    if not sql or not sql.strip():
        return ValidationResult(False, errors=["empty SQL"])
    if len(sql) > max_chars:
        return ValidationResult(False, errors=[f"SQL longer than {max_chars} characters"])

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        return ValidationResult(False, errors=[f"could not parse SQL: {str(exc).splitlines()[0]}"])
    if len(statements) != 1:
        return ValidationResult(False, errors=[f"exactly one statement allowed, got {len(statements)}"])
    tree = statements[0]

    errors: list[str] = []
    if not isinstance(tree, QUERY_ROOTS):
        errors.append(f"only SELECT queries are allowed, got {tree.key.upper()}")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            errors.append(f"forbidden operation: {node.key.upper()}")
        if isinstance(node, exp.Select) and node.args.get("locks"):
            errors.append("row locking (FOR UPDATE/SHARE) is not allowed")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if (
                name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES) or "generate_series" in name
            ):  # sqlglot: ExplodingGenerateSeries
                errors.append(f"function not allowed: {name}")

    ctes = _cte_names(tree)
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = table.db.lower()
        if table.catalog:
            errors.append(f"cross-database reference not allowed: {table.sql()}")
            continue
        if not name:  # e.g. a function in FROM: caught by the function checks
            if not isinstance(table.this, exp.Func):
                errors.append(f"unsupported FROM item: {table.sql()}")
            continue
        if not schema and name in ctes:
            continue
        if schema and schema != APPROVED_SCHEMA:
            errors.append(f"schema not allowed: {schema} (only {APPROVED_SCHEMA})")
            continue
        if name not in APPROVED_TABLES:
            errors.append(f"table not allowed: {table.sql()} (allowed: {', '.join(sorted(APPROVED_TABLES))})")
            continue
        if not schema:
            table.set("db", exp.to_identifier(APPROVED_SCHEMA))  # qualify, independent of search_path
        tables.add(f"{APPROVED_SCHEMA}.{name}")

    if errors:
        return ValidationResult(False, errors=list(dict.fromkeys(errors)))

    # Enforce a row limit on the outermost query.
    limit_applied = False
    current = _limit_value(tree)
    if current is None or current < 0 or current > max_rows:
        tree = tree.limit(max_rows, copy=False) if current is None else tree
        if current is not None:
            tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        limit_applied = True

    return ValidationResult(True, sql=tree.sql(dialect="postgres"), tables=sorted(tables), limit_applied=limit_applied)
