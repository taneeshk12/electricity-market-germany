"""Clean raw SMARD chunks and aggregate them to an hourly UTC grid.

Key decisions (see docs/data_quality_report.md for the numbers):

* Time handling – SMARD's API delivers epoch milliseconds, i.e. UTC instants.
  We keep UTC as the primary key, which makes DST trivial: the 23h spring day
  and 25h autumn day are simply 23/25 consecutive UTC hours. A local
  Europe/Berlin timestamp plus its UTC offset is derived for reporting
  (the offset disambiguates the repeated 02:00 hour in October).
* Resolution – raw data is quarter-hourly. We detect the step size from the
  timestamps, and for prices we also detect the *effective* resolution: until
  the day-ahead market moved to 15-minute products, all four quarter-hours of
  an hour carry the same price.
* Aggregation to hours – volumes (MWh per interval) are SUMMED, prices
  (EUR/MWh) are AVERAGED (unweighted mean, which matches SMARD's own hourly
  price series). An hour is only aggregated if all 4 quarter-hours are
  present; otherwise it stays NaN. Nothing is interpolated or filled.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src import config
from src.extract import chunk_dir

logger = logging.getLogger(__name__)

QUARTERS_PER_HOUR = 4
GENERATION_FILE = config.PROCESSED_DIR / "generation_hourly.parquet"
PRICE_LOAD_FILE = config.PROCESSED_DIR / "price_load_hourly.parquet"
REFERENCE_FILE = config.PROCESSED_DIR / "smard_hourly_reference.parquet"
METADATA_FILE = config.PROCESSED_DIR / "transform_metadata.json"


@dataclass
class SeriesStats:
    """Per-series bookkeeping that feeds the data quality report."""

    name: str
    raw_points: int = 0
    duplicate_timestamps: int = 0
    conflicting_duplicates: int = 0
    non_numeric_values: int = 0
    null_quarters: int = 0
    step_minutes: float | None = None
    effective_15min_from: str | None = None  # prices only: first local date with intra-hour variation
    incomplete_hours: int = 0                 # hours with 1–3 of 4 quarters -> set to NaN
    missing_hours: int = 0                    # hours without any value after aggregation


def load_raw_series(series: config.SmardSeries, resolution: str, stats: SeriesStats | None = None) -> pd.Series:
    """Read all weekly chunks of one series into a UTC-indexed float Series."""
    files = sorted(chunk_dir(series, resolution).glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No raw chunks for {series.name}/{resolution} – run extract first")

    frames = [
        pd.DataFrame(json.loads(f.read_text())["series"], columns=["ts_ms", "value"]) for f in files
    ]
    df = pd.concat(frames, ignore_index=True)

    # Coerce to numbers; anything non-numeric (e.g. "-") becomes NaN and is counted.
    numeric = pd.to_numeric(df["value"], errors="coerce")
    non_numeric = int((numeric.isna() & df["value"].notna()).sum())
    df["value"] = numeric
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)

    # Duplicates can only arise from overlapping chunks; identical ones are harmless.
    dup_mask = df.duplicated("ts", keep=False)
    conflicting = int(df[dup_mask].groupby("ts")["value"].nunique(dropna=False).gt(1).sum())
    duplicates = int(df.duplicated("ts").sum())
    if conflicting:
        logger.warning("%s/%s: %d timestamps with conflicting duplicate values (keeping last)",
                       series.name, resolution, conflicting)
    df = df.drop_duplicates("ts", keep="last").set_index("ts").sort_index()

    start, end = config.period_bounds_utc()
    out = df.loc[(df.index >= start) & (df.index < end), "value"].rename(series.name)

    if stats is not None:
        stats.raw_points = len(out)
        stats.duplicate_timestamps = duplicates
        stats.conflicting_duplicates = conflicting
        stats.non_numeric_values = non_numeric
        stats.null_quarters = int(out.isna().sum())
        steps = out.index.to_series().diff().dropna().dt.total_seconds() / 60
        stats.step_minutes = float(steps.mode().iloc[0]) if not steps.empty else None
    return out


def detect_effective_15min_start(price_q: pd.Series) -> str | None:
    """Return the first local date on which quarter-hour prices differ within an hour.

    Before the switch to 15-minute day-ahead products, SMARD repeats the hourly
    price in all four quarters, so the number of distinct values per hour is 1.
    """
    distinct = price_q.dropna().groupby(price_q.dropna().index.floor("h")).nunique()
    varying = distinct[distinct > 1]
    if varying.empty:
        return None
    return varying.index[0].tz_convert(config.LOCAL_TZ).date().isoformat()


def aggregate_hourly(q: pd.Series, how: str, stats: SeriesStats) -> pd.Series:
    """Aggregate a quarter-hour series to a complete hourly UTC grid.

    Floor-to-hour in UTC is safe because Europe/Berlin offsets are whole hours.
    Hours with fewer than 4 valid quarters become NaN (no partial sums/means).
    """
    hour = q.index.floor("h")
    grouped = q.groupby(hour)
    counts = grouped.count()
    agg = grouped.sum(min_count=1) if how == "sum" else grouped.mean()
    complete = counts == QUARTERS_PER_HOUR
    stats.incomplete_hours = int(((counts > 0) & ~complete).sum())
    agg = agg.where(complete)

    start, end = config.period_bounds_utc()
    grid = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC", name="timestamp_utc")
    agg = agg.reindex(grid)
    stats.missing_hours = int(agg.isna().sum())
    return agg


def add_local_time(df: pd.DataFrame) -> pd.DataFrame:
    """Add Europe/Berlin wall-clock time and UTC offset next to the UTC key."""
    local = df["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ)
    df.insert(1, "timestamp_local", local.dt.tz_localize(None))
    df.insert(2, "utc_offset_h", (local.map(lambda t: t.utcoffset().total_seconds() / 3600)).astype("int8"))
    return df


def build_reference(series_list: tuple[config.SmardSeries, ...]) -> pd.DataFrame:
    """SMARD's own hourly series in long format – used only to reconcile our aggregation."""
    frames = []
    for s in series_list:
        ref = load_raw_series(s, "hour")
        frames.append(pd.DataFrame({"timestamp_utc": ref.index, "series": s.name, "value": ref.to_numpy()}))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    """Run the full transform and write parquet files to data/processed/."""
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    hourly: dict[str, pd.Series] = {}
    all_stats: list[SeriesStats] = []

    for s in config.SMARD_SERIES:
        stats = SeriesStats(s.name)
        q = load_raw_series(s, "quarterhour", stats)
        if s.kind == "price":
            stats.effective_15min_from = detect_effective_15min_start(q)
            logger.info("%s: effective 15-min prices from %s", s.name, stats.effective_15min_from)
        hourly[s.name] = aggregate_hourly(q, "mean" if s.kind == "price" else "sum", stats)
        all_stats.append(stats)
        logger.info("%-20s step=%smin quarters=%d null=%d incomplete_h=%d missing_h=%d",
                    s.name, stats.step_minutes, stats.raw_points, stats.null_quarters,
                    stats.incomplete_hours, stats.missing_hours)

    # Generation -> long format (timestamp, source, mwh). NaN rows are kept on purpose
    # so missing data stays visible; the load step decides how to treat them.
    gen_names = [s.name for s in config.SMARD_SERIES if s.kind == "generation"]
    wide = pd.DataFrame({n: hourly[n] for n in gen_names})
    generation = (
        wide.rename_axis("timestamp_utc").reset_index()
        .melt(id_vars="timestamp_utc", var_name="source", value_name="generation_mwh")
        .sort_values(["timestamp_utc", "source"], ignore_index=True)
    )
    generation = add_local_time(generation)

    price_load = pd.DataFrame({
        "price_eur_mwh": hourly["day_ahead_price"],
        "consumption_mwh": hourly["grid_load"],
    }).rename_axis("timestamp_utc").reset_index()
    price_load = add_local_time(price_load)

    generation.to_parquet(GENERATION_FILE, index=False)
    price_load.to_parquet(PRICE_LOAD_FILE, index=False)
    build_reference(config.SMARD_SERIES).to_parquet(REFERENCE_FILE, index=False)
    METADATA_FILE.write_text(json.dumps([asdict(s) for s in all_stats], indent=2))
    logger.info("Wrote %s (%d rows) and %s (%d rows)",
                GENERATION_FILE.name, len(generation), PRICE_LOAD_FILE.name, len(price_load))


if __name__ == "__main__":
    config.setup_logging()
    main()
