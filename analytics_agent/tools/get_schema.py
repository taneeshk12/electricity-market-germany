"""Tool: describe the approved tables and columns."""

from __future__ import annotations

from typing import Any

from analytics_agent import schema_context


def get_database_schema() -> dict[str, Any]:
    """Approved tables (schema `marts` only) with column types and business descriptions."""
    return schema_context.as_dict()
