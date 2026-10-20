"""Run every query in sql/analysis/ and save the results.

Outputs
  docs/analysis_results/<query>.csv   full result of each query
  docs/analysis_results.md            all results in one file (long results truncated)

Findings in the README are taken from these files only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from src import config
from src.load import get_engine
from src.reporting import df_to_markdown

logger = logging.getLogger(__name__)

ANALYSIS_DIR = config.SQL_DIR / "analysis"
RESULTS_DIR = config.DOCS_DIR / "analysis_results"
RESULTS_MD = config.DOCS_DIR / "analysis_results.md"
MAX_ROWS_IN_MD = 40


def _header_comment(sql: str) -> str:
    """The leading '--' comment block of a query, used as its description."""
    lines = []
    for line in sql.splitlines():
        if not line.startswith("--"):
            break
        lines.append(line.lstrip("- ").rstrip())
    return " ".join(lines)


def main() -> None:
    """Execute all analysis queries in file order and write CSV + markdown."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    sections = []
    with engine.connect() as conn:
        for path in sorted(ANALYSIS_DIR.glob("*.sql")):
            sql = path.read_text()
            df = pd.read_sql(text(sql), conn)
            df.to_csv(RESULTS_DIR / f"{path.stem}.csv", index=False)
            shown = df if len(df) <= MAX_ROWS_IN_MD else df.head(MAX_ROWS_IN_MD)
            note = "" if shown is df else f"\n\n*Showing {MAX_ROWS_IN_MD} of {len(df)} rows – full result in `analysis_results/{path.stem}.csv`.*"
            sections.append(
                f"## {path.stem}\n\n{_header_comment(sql)}\n\n"
                f"Query: [`sql/analysis/{path.name}`](../sql/analysis/{path.name})\n\n"
                f"{df_to_markdown(shown, index=False)}{note}\n"
            )
            logger.info("%-40s %5d rows", path.name, len(df))

    RESULTS_MD.write_text(
        "# Analysis results\n\n"
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from the PostgreSQL star schema "
        "by `src/run_analysis.py`.\n\n" + "\n".join(sections)
    )
    logger.info("Results written to %s", RESULTS_MD)


if __name__ == "__main__":
    config.setup_logging()
    main()
