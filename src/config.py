"""Central configuration: paths, period, and database connection settings.

All values are read from environment variables (via .env) so nothing secret
or machine-specific is hard-coded.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

RAW_DIR: Path = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR: Path = PROJECT_ROOT / "data" / "processed"
SQL_DIR: Path = PROJECT_ROOT / "sql"
DOCS_DIR: Path = PROJECT_ROOT / "docs"

# SMARD publishes timestamps in German local time; all conversions go through this zone.
LOCAL_TZ: str = "Europe/Berlin"

START_DATE: date = date.fromisoformat(os.getenv("START_DATE", "2023-01-01"))
END_DATE: date = date.fromisoformat(os.getenv("END_DATE", "2025-12-31"))


@dataclass(frozen=True)
class DbSettings:
    """Connection settings for the PostgreSQL instance from docker-compose."""

    user: str
    password: str
    host: str
    port: int
    database: str

    @property
    def url(self) -> str:
        """SQLAlchemy connection URL (psycopg2 driver)."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


def get_db_settings() -> DbSettings:
    """Build DB settings from the environment, failing loudly if a value is missing."""
    try:
        return DbSettings(
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5433")),
            database=os.environ["POSTGRES_DB"],
        )
    except KeyError as exc:
        raise RuntimeError(
            f"Missing environment variable {exc}. Copy .env.example to .env first."
        ) from exc


def setup_logging() -> None:
    """Configure root logging once for all pipeline scripts."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
