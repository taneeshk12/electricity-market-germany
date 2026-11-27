"""Export daily DE-LU day-ahead prices from the PostgreSQL warehouse.

The daily grain is the local (Europe/Berlin) calendar day, aggregated from the hourly
view `v_hourly`. DST days have 23 or 25 hours; the base price is the simple mean of the
hours that exist, which matches how exchanges quote a daily base index.

Usage:
    python -m risk_workbook.export                     # warehouse -> CSV
    python -m risk_workbook.export --source parquet    # no database: use data/processed
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from src.config import PROCESSED_DIR, PROJECT_ROOT, get_db_settings, setup_logging

log = logging.getLogger(__name__)

OUTPUT_DIR: Path = PROJECT_ROOT / "risk_workbook" / "output"
DAILY_CSV: Path = OUTPUT_DIR / "prices_daily.csv"

# Column order is the contract with the workbook (Data sheet) and the VBA refresh macro.
DAILY_COLUMNS: list[str] = [
    "date",
    "year",
    "month",
    "weekday",
    "day_type",
    "base_price",
    "peak_price",
    "min_price",
    "max_price",
    "negative_hours",
    "load_gwh",
    "renewable_share",
]

DAILY_SQL = """
SELECT
    dd.date                                                        AS date,
    dd.year                                                        AS year,
    dd.month                                                       AS month,
    dd.weekday_name                                                AS weekday,
    CASE WHEN dd.is_public_holiday THEN 'Holiday'
         WHEN dd.is_weekend        THEN 'Weekend'
         ELSE 'Weekday' END                                        AS day_type,
    AVG(h.price_eur_mwh)                                           AS base_price,
    AVG(h.price_eur_mwh) FILTER (WHERE h.is_peak)                  AS peak_price,
    MIN(h.price_eur_mwh)                                           AS min_price,
    MAX(h.price_eur_mwh)                                           AS max_price,
    COUNT(*) FILTER (WHERE h.price_eur_mwh < 0)                    AS negative_hours,
    SUM(h.consumption_mwh) / 1000.0                                AS load_gwh,
    SUM(h.renewable_mwh) / NULLIF(SUM(h.total_gen_mwh), 0)         AS renewable_share
FROM v_hourly h
JOIN dim_date dd USING (date_key)
GROUP BY dd.date, dd.year, dd.month, dd.weekday_name, dd.is_public_holiday, dd.is_weekend
ORDER BY dd.date
"""


def load_daily_from_warehouse() -> pd.DataFrame:
    """Aggregate hourly warehouse data to one row per local day."""
    engine = create_engine(get_db_settings().url)
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(DAILY_SQL), conn)
    finally:
        engine.dispose()
    return _tidy(df)


def load_daily_from_parquet(processed_dir: Path = PROCESSED_DIR) -> pd.DataFrame:
    """Same daily table from the processed parquet files, for use without a database.

    Day type here only knows weekends; public holidays live in the warehouse calendar.
    """
    pl = pd.read_parquet(processed_dir / "price_load_hourly.parquet")
    gen = pd.read_parquet(processed_dir / "generation_hourly.parquet")
    pl = pl.assign(date=pl["timestamp_local"].dt.date)
    ts = pl["timestamp_local"]
    pl["is_peak"] = (ts.dt.weekday < 5) & ts.dt.hour.between(8, 19)
    daily = pl.groupby("date").agg(
        base_price=("price_eur_mwh", "mean"),
        min_price=("price_eur_mwh", "min"),
        max_price=("price_eur_mwh", "max"),
        negative_hours=("price_eur_mwh", lambda s: int((s < 0).sum())),
        load_gwh=("consumption_mwh", lambda s: s.sum() / 1000.0),
    )
    daily["peak_price"] = pl[pl["is_peak"]].groupby("date")["price_eur_mwh"].mean()
    daily["renewable_share"] = _renewable_share_from_parquet(gen)
    daily = daily.reset_index()
    d = pd.to_datetime(daily["date"])
    daily["year"] = d.dt.year
    daily["month"] = d.dt.month
    daily["weekday"] = d.dt.day_name()
    daily["day_type"] = d.dt.weekday.map(lambda w: "Weekend" if w >= 5 else "Weekday")
    return _tidy(daily)


RENEWABLE_SOURCES = {"wind_onshore", "wind_offshore", "solar", "biomass", "hydro", "other_renewable"}


def _renewable_share_from_parquet(gen: pd.DataFrame) -> pd.Series:
    gen = gen.assign(date=gen["timestamp_local"].dt.date)
    totals = gen.groupby("date")["generation_mwh"].sum()
    ren = gen[gen["source"].isin(RENEWABLE_SOURCES)].groupby("date")["generation_mwh"].sum()
    return ren / totals


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    df = df[DAILY_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"])
    for col in ["year", "month", "negative_hours"]:
        df[col] = df[col].astype(int)
    for col in ["base_price", "peak_price", "min_price", "max_price", "load_gwh"]:
        df[col] = df[col].astype(float).round(2)
    df["renewable_share"] = df["renewable_share"].astype(float).round(4)
    return df.sort_values("date").reset_index(drop=True)


def write_csv(df: pd.DataFrame, path: Path = DAILY_CSV) -> Path:
    """Write the daily table as CSV (ISO dates, '.' decimals): the VBA refresh macro reads this file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, date_format="%Y-%m-%d")
    return path


def main(argv: list[str] | None = None) -> pd.DataFrame:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["warehouse", "parquet"], default="warehouse")
    parser.add_argument("--out", type=Path, default=DAILY_CSV)
    args = parser.parse_args(argv)

    setup_logging()
    df = load_daily_from_warehouse() if args.source == "warehouse" else load_daily_from_parquet()
    path = write_csv(df, args.out)
    log.info(
        "Exported %d days (%s to %s) from %s -> %s",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
        args.source,
        path,
    )
    return df


if __name__ == "__main__":
    main()
