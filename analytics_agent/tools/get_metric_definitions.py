"""Tool: return the approved metric catalogue."""

from __future__ import annotations

from typing import Any

from analytics_agent import metrics


def get_metric_definitions() -> dict[str, Any]:
    """Approved business metrics with definition, formula, tables, unit and limitations."""
    return {"metrics": metrics.as_dict()}
