"""MCP server exposing the warehouse to any MCP client (stdio by default).

    python -m analytics_agent.server            # stdio, e.g. for Claude Desktop / MCP Inspector

The same server object is used in-process by the agent (analytics_agent.agent), so the
Streamlit app and external MCP clients go through identical tools and safeguards.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from analytics_agent.tools import execute_query, get_metric_definitions, get_schema

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    "electricity-market-germany",
    instructions=(
        "Read-only analytics over hourly German electricity market data (SMARD, DE-LU, 2023–2025). "
        "Call get_database_schema and get_metric_definitions before writing SQL. "
        "execute_readonly_query only accepts a single SELECT on schema marts."
    ),
)


@server.tool(annotations=READ_ONLY)
def get_database_schema() -> dict[str, Any]:
    """Approved tables and columns (schema marts) with types and business descriptions."""
    return get_schema.get_database_schema()


@server.tool(name="get_metric_definitions", annotations=READ_ONLY)
def get_metric_definitions_tool() -> dict[str, Any]:
    """Approved business metrics: definition, formula, tables, columns, unit, limitations."""
    return get_metric_definitions.get_metric_definitions()


@server.tool(annotations=READ_ONLY)
def execute_readonly_query(sql: str) -> dict[str, Any]:
    """Validate and run ONE PostgreSQL SELECT on schema marts as a read-only role.

    Returns columns, rows (max AGENT_MAX_ROWS), truncated flag and timing, or an error.
    """
    return execute_query.execute_readonly_query(sql)


@server.tool(annotations=READ_ONLY)
def get_available_date_range() -> dict[str, Any]:
    """First and last date/hour available in the warehouse."""
    return execute_query.get_available_date_range()


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
