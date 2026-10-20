"""Load the processed hourly data into the PostgreSQL star schema.

Strategy (idempotent, all-or-nothing):
1. Apply sql/01_schema.sql and sql/02_dim_date.sql (CREATE IF NOT EXISTS / upserts).
2. Fill dim_date via the SQL procedure and cross-check holidays against Python's `holidays`.
3. For dim_datetime and both facts: COPY the DataFrame into a temp staging table,
   upsert into the target (ON CONFLICT ... DO UPDATE, only where values changed),
   then delete target rows that are no longer in the source (sync semantics).
Everything runs in ONE transaction, so a failed load leaves the database unchanged.

Rows without a value (e.g. nuclear after its series ended, the few incomplete
hours) are not loaded into fact_hourly: a missing row means "no data".
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import holidays
import pandas as pd
from psycopg2.extensions import cursor as PgCursor
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src import config
from src.transform import GENERATION_FILE, PRICE_LOAD_FILE

logger = logging.getLogger(__name__)

SCHEMA_FILES: tuple[Path, ...] = (config.SQL_DIR / "01_schema.sql", config.SQL_DIR / "02_dim_date.sql")
PEAK_HOURS = range(8, 20)  # 08:00–20:00 local, Mon–Fri


def get_engine() -> Engine:
    """SQLAlchemy engine for the configured database."""
    return create_engine(config.get_db_settings().url, future=True)


def _timestamp_key(ts_utc: pd.Series) -> pd.Series:
    """yyyymmddhh of the UTC hour start as int64."""
    return ts_utc.dt.strftime("%Y%m%d%H").astype("int64")


def _add_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Add timestamp_key (UTC), date_key and hour_key (local) to a processed frame."""
    out = df.copy()
    out["timestamp_key"] = _timestamp_key(out["timestamp_utc"])
    out["date_key"] = out["timestamp_local"].dt.strftime("%Y%m%d").astype("int32")
    out["hour_key"] = out["timestamp_local"].dt.hour.astype("int16")
    return out


def build_dim_datetime(price_load: pd.DataFrame) -> pd.DataFrame:
    """One row per UTC hour of the analysis period (the price/load grid is complete)."""
    df = _add_keys(price_load)
    local = df["timestamp_local"]
    df["is_peak"] = (local.dt.weekday < 5) & local.dt.hour.isin(PEAK_HOURS)
    return df[["timestamp_key", "timestamp_utc", "timestamp_local", "utc_offset_h",
               "date_key", "hour_key", "is_peak"]]


def build_fact_price_load(price_load: pd.DataFrame) -> pd.DataFrame:
    """Hourly price and grid load with keys; NaN stays NULL."""
    df = _add_keys(price_load)
    df["price_eur_mwh"] = df["price_eur_mwh"].round(4)
    df["consumption_mwh"] = df["consumption_mwh"].round(3)
    return df[["timestamp_key", "date_key", "hour_key", "price_eur_mwh", "consumption_mwh"]]


def build_fact_hourly(generation: pd.DataFrame, source_keys: dict[str, int]) -> pd.DataFrame:
    """Long-format generation with keys; rows without a value are dropped."""
    unknown = set(generation["source"]) - set(source_keys)
    if unknown:
        raise ValueError(f"Sources missing in dim_source: {sorted(unknown)}")
    df = generation.dropna(subset=["generation_mwh"])
    logger.info("fact_hourly: dropping %d rows without a value (of %d)",
                len(generation) - len(df), len(generation))
    df = _add_keys(df)
    df["source_key"] = df["source"].map(source_keys).astype("int16")
    df["generation_mwh"] = df["generation_mwh"].round(3)
    return df[["timestamp_key", "date_key", "hour_key", "source_key", "generation_mwh"]]


def sync_table(cur: PgCursor, table: str, df: pd.DataFrame, key_cols: list[str],
               delete_stale: bool = True) -> dict[str, int]:
    """Make `table` match `df`: COPY to staging, upsert changed rows, optionally delete stale rows.

    The staging table lives until COMMIT, so `delete_stale_rows` can be called later
    (needed for dimensions, whose stale rows may only go after the facts referencing them).
    """
    cols = list(df.columns)
    value_cols = [c for c in cols if c not in key_cols]
    col_list, key_list = ", ".join(cols), ", ".join(key_cols)
    stage = f"stg_{table}"

    cur.execute(f"CREATE TEMP TABLE {stage} (LIKE {table}) ON COMMIT DROP")
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="", date_format="%Y-%m-%d %H:%M:%S%z")
    buf.seek(0)
    cur.copy_expert(f"COPY {stage} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)

    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in value_cols)
    changed = " OR ".join(f"{table}.{c} IS DISTINCT FROM EXCLUDED.{c}" for c in value_cols)
    cur.execute(
        f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {stage} "
        f"ON CONFLICT ({key_list}) DO UPDATE SET {set_clause} WHERE {changed}"
    )
    upserted = cur.rowcount
    deleted = delete_stale_rows(cur, table, key_cols) if delete_stale else 0
    logger.info("%-16s staged=%d inserted/updated=%d deleted=%d", table, len(df), upserted, deleted)
    return {"staged": len(df), "upserted": upserted, "deleted": deleted}


def delete_stale_rows(cur: PgCursor, table: str, key_cols: list[str]) -> int:
    """Delete rows of `table` that are not in its staging table (source no longer has them)."""
    join = " AND ".join(f"s.{c} = t.{c}" for c in key_cols)
    cur.execute(f"DELETE FROM {table} t WHERE NOT EXISTS (SELECT 1 FROM stg_{table} s WHERE {join})")
    return cur.rowcount


def check_holidays(cur: PgCursor) -> None:
    """Cross-check SQL holiday logic against the `holidays` package (nationwide only)."""
    cur.execute("SELECT date FROM dim_date WHERE is_public_holiday")
    sql_days = {r[0] for r in cur.fetchall()}
    years = range(config.START_DATE.year, config.END_DATE.year + 1)
    py_days = {d for d in holidays.Germany(years=years) if config.START_DATE <= d <= config.END_DATE}
    if sql_days != py_days:
        raise RuntimeError(f"Holiday mismatch: only SQL {sorted(sql_days - py_days)}, "
                           f"only Python {sorted(py_days - sql_days)}")
    logger.info("dim_date: %d public holidays, identical to Python 'holidays' package", len(sql_days))


def main() -> None:
    """Run the full, transactional load."""
    generation = pd.read_parquet(GENERATION_FILE)
    price_load = pd.read_parquet(PRICE_LOAD_FILE)
    engine = get_engine()

    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            for path in SCHEMA_FILES:
                cur.execute(path.read_text())
                logger.info("Applied %s", path.name)
            cur.execute("CALL fill_dim_date(%s, %s)", (config.START_DATE, config.END_DATE))
            check_holidays(cur)

            cur.execute("SELECT source_name, source_key FROM dim_source")
            source_keys = dict(cur.fetchall())

            # FK order: upsert the dimension first, sync the facts, and only then remove
            # dimension rows that no fact may reference any more.
            sync_table(cur, "dim_datetime", build_dim_datetime(price_load), ["timestamp_key"],
                       delete_stale=False)
            sync_table(cur, "fact_price_load", build_fact_price_load(price_load), ["timestamp_key"])
            sync_table(cur, "fact_hourly", build_fact_hourly(generation, source_keys),
                       ["timestamp_key", "source_key"])
            logger.info("dim_datetime     deleted=%d stale rows",
                        delete_stale_rows(cur, "dim_datetime", ["timestamp_key"]))
        raw.commit()
    except Exception:
        raw.rollback()
        logger.exception("Load failed – transaction rolled back")
        raise
    finally:
        raw.close()

    with engine.connect() as conn:
        for table in ("dim_date", "dim_hour", "dim_source", "dim_datetime", "fact_hourly", "fact_price_load"):
            n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            logger.info("%-16s %8d rows", table, n)


if __name__ == "__main__":
    config.setup_logging()
    main()
