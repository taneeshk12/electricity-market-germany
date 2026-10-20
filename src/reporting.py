"""Small helpers shared by the report-writing scripts."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd


def _fmt(value: object) -> str:
    """Format one cell: thousands separators for numbers, empty string for NULL."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, (float, Decimal)):
        return f"{value:,.2f}"
    return str(value)


def df_to_markdown(df: pd.DataFrame, index: bool = True) -> str:
    """Render a DataFrame as a GitHub markdown table (no tabulate dependency)."""
    if index:
        df = df.reset_index()
    if "year" in df.columns:
        df = df.assign(year=df["year"].astype(str))  # avoid "2,023" from thousands formatting
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)
