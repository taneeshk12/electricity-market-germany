"""Central configuration: paths, period, and database connection settings.

All values are read from environment variables (via .env) so nothing secret
or machine-specific is hard-coded.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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


def period_bounds_utc() -> tuple[datetime, datetime]:
    """Start/end of the analysis period (local German dates) as UTC instants, end exclusive."""
    tz = ZoneInfo(LOCAL_TZ)
    start = datetime.combine(START_DATE, datetime.min.time(), tz)
    end = datetime.combine(END_DATE + timedelta(days=1), datetime.min.time(), tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

# --- SMARD chart-data API -------------------------------------------------------
# Public JSON endpoints behind the smard.de charts (documented by bundesAPI/smard-api).
# Each series is split into weekly chunks; an index file lists the chunk start times.
SMARD_BASE_URL: str = "https://www.smard.de/app/chart_data"
# Market area Germany/Luxembourg = the day-ahead bidding zone, so volumes and price match.
SMARD_REGION: str = "DE-LU"
# Quarter-hour is the finest resolution and lets us detect the 2025 switch to 15-min prices;
# SMARD's own hourly series is downloaded too, only to reconcile our aggregation against it.
SMARD_RESOLUTIONS: tuple[str, ...] = ("quarterhour", "hour")


@dataclass(frozen=True)
class SmardSeries:
    """One SMARD time series (filter id) and how it maps into our model."""

    filter_id: int
    name: str          # snake_case name used throughout the pipeline
    kind: str          # "generation" | "consumption" | "price"
    unit: str          # unit per interval as delivered by SMARD


# Generation: "Stromerzeugung – realisiert"; units are MWh per interval.
SMARD_SERIES: tuple[SmardSeries, ...] = (
    SmardSeries(1223, "lignite", "generation", "MWh"),
    SmardSeries(1224, "nuclear", "generation", "MWh"),
    SmardSeries(1225, "wind_offshore", "generation", "MWh"),
    SmardSeries(1226, "hydro", "generation", "MWh"),
    SmardSeries(1227, "other_conventional", "generation", "MWh"),
    SmardSeries(1228, "other_renewable", "generation", "MWh"),
    SmardSeries(4066, "biomass", "generation", "MWh"),
    SmardSeries(4067, "wind_onshore", "generation", "MWh"),
    SmardSeries(4068, "solar", "generation", "MWh"),
    SmardSeries(4069, "hard_coal", "generation", "MWh"),
    SmardSeries(4070, "pumped_storage", "generation", "MWh"),
    SmardSeries(4071, "natural_gas", "generation", "MWh"),
    # Consumption: "Stromverbrauch – realisierter Stromverbrauch: Gesamt (Netzlast)".
    SmardSeries(410, "grid_load", "consumption", "MWh"),
    # Day-ahead price for bidding zone DE/LU.
    SmardSeries(4169, "day_ahead_price", "price", "EUR/MWh"),
)


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
