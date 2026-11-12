"""Transform: cleaning, DST handling and quarter-hour -> hour aggregation."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from src import config, transform
from tests.conftest import LOAD, PRICE, SOLAR, TEST_SERIES, quarter_index, to_ms


def _q(start: str, values: list) -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="15min", tz="UTC")
    return pd.Series(values, index=idx, dtype="float64")


# --- load_raw_series ------------------------------------------------------------------


def test_load_raw_series_cleans_duplicates_and_non_numeric(write_chunks, autumn_period) -> None:
    q = quarter_index(*autumn_period)
    ms = to_ms(q)
    # Two overlapping chunks: ms[1] duplicated with the same value, ms[2] with a conflicting value.
    write_chunks(
        SOLAR, "quarterhour", [(ms[0], 1.0), (ms[1], 2.0), (ms[2], 3.0), (ms[3], "-"), (ms[4], None)], chunk_ms=0
    )
    write_chunks(SOLAR, "quarterhour", [(ms[1], 2.0), (ms[2], 99.0)], chunk_ms=1)
    stats = transform.SeriesStats("solar")
    out = transform.load_raw_series(SOLAR, "quarterhour", stats)

    assert out.index.is_unique and out.index.is_monotonic_increasing
    assert out.index.tz is not None and str(out.index.tz) == "UTC"
    assert stats.duplicate_timestamps == 2
    assert stats.conflicting_duplicates == 1
    assert out.loc[q[2]] == 99.0  # conflicting duplicate: later chunk wins (documented behaviour)
    assert stats.non_numeric_values == 1  # "-" coerced to NaN and counted
    assert stats.null_quarters == 2  # the coerced "-" plus the JSON null
    assert stats.step_minutes == 15.0


def test_load_raw_series_filters_to_period(write_chunks, autumn_period) -> None:
    q = quarter_index(*autumn_period)
    before = q[0] - pd.Timedelta(minutes=15)
    after = q[-1] + pd.Timedelta(minutes=15)
    write_chunks(SOLAR, "quarterhour", [(m, 1.0) for m in to_ms(pd.DatetimeIndex([before, q[0], q[-1], after]))])
    out = transform.load_raw_series(SOLAR, "quarterhour")
    assert list(out.index) == [q[0], q[-1]]


def test_load_raw_series_without_chunks_raises(raw_dir) -> None:
    with pytest.raises(FileNotFoundError, match="run extract first"):
        transform.load_raw_series(SOLAR, "quarterhour")


# --- aggregate_hourly -----------------------------------------------------------------


def test_aggregate_sums_volumes_and_averages_prices(autumn_period) -> None:
    start, _ = config.period_bounds_utc()
    q = _q(str(start), [1, 2, 3, 4, 10, 20, 30, 40])
    vol = transform.aggregate_hourly(q, "sum", transform.SeriesStats("v"))
    price = transform.aggregate_hourly(q, "mean", transform.SeriesStats("p"))
    assert vol.iloc[:2].tolist() == [10.0, 100.0]
    assert price.iloc[:2].tolist() == [2.5, 25.0]


def test_incomplete_hours_become_nan_and_are_never_filled(autumn_period) -> None:
    start, _ = config.period_bounds_utc()
    q = _q(str(start), [1, 2, 3, 4, 5, 6, 7])  # second hour has only 3 quarters
    stats = transform.SeriesStats("v")
    out = transform.aggregate_hourly(q, "sum", stats)
    assert out.iloc[0] == 10.0
    assert math.isnan(out.iloc[1])
    assert stats.incomplete_hours == 1
    # Every hour of the 3-day grid except the first one is missing.
    assert stats.missing_hours == len(out) - 1


def test_all_null_hour_is_nan_not_zero(autumn_period) -> None:
    start, _ = config.period_bounds_utc()
    out = transform.aggregate_hourly(_q(str(start), [None] * 4), "sum", transform.SeriesStats("v"))
    assert math.isnan(out.iloc[0])


@pytest.mark.parametrize(
    ("period_fixture", "dst_day", "hours_that_day", "grid_hours"),
    [
        ("autumn_period", "2024-10-27", 25, 24 + 25 + 24),
        ("spring_period", "2024-03-31", 23, 24 + 23 + 24),
    ],
)
def test_hourly_grid_on_dst_days(request, period_fixture, dst_day, hours_that_day, grid_hours) -> None:
    request.getfixturevalue(period_fixture)
    q = pd.Series(1.0, index=quarter_index(*request.getfixturevalue(period_fixture)))
    out = transform.aggregate_hourly(q, "sum", stats := transform.SeriesStats("v"))
    assert len(out) == grid_hours
    assert stats.missing_hours == 0 and stats.incomplete_hours == 0
    local_days = out.index.tz_convert(config.LOCAL_TZ).date
    assert (local_days == pd.Timestamp(dst_day).date()).sum() == hours_that_day


def test_detect_effective_15min_start() -> None:
    hourly_constant = _q("2025-09-30 20:00", [50, 50, 50, 50, 60, 60, 60, 60])
    assert transform.detect_effective_15min_start(hourly_constant) is None
    switched = _q("2025-09-30 22:00", [50, 50, 50, 50, 60, 61, 62, 63])  # 2nd hour = 2025-10-01 01:00 local
    assert transform.detect_effective_15min_start(switched) == "2025-10-01"


# --- add_local_time (DST regression) --------------------------------------------------


def test_add_local_time_disambiguates_repeated_autumn_hour() -> None:
    utc = pd.date_range("2024-10-26 23:00", "2024-10-27 02:00", freq="h", tz="UTC")
    df = transform.add_local_time(pd.DataFrame({"timestamp_utc": utc}))
    assert list(df.columns[:3]) == ["timestamp_utc", "timestamp_local", "utc_offset_h"]
    local = df["timestamp_local"].dt.strftime("%H:%M").tolist()
    assert local == ["01:00", "02:00", "02:00", "03:00"]  # 02:00 local occurs twice
    assert df["utc_offset_h"].tolist() == [2, 2, 1, 1]  # ...distinguished by the UTC offset
    assert df["timestamp_utc"].is_unique


def test_add_local_time_skips_spring_hour() -> None:
    utc = pd.date_range("2024-03-31 00:00", "2024-03-31 01:00", freq="h", tz="UTC")
    df = transform.add_local_time(pd.DataFrame({"timestamp_utc": utc}))
    assert df["timestamp_local"].dt.strftime("%H:%M").tolist() == ["01:00", "03:00"]  # 02:00 does not exist
    assert df["utc_offset_h"].tolist() == [1, 2]


# --- end to end -----------------------------------------------------------------------


def test_transform_main_end_to_end(synthetic_raw, processed_dir, autumn_period) -> None:
    transform.main()
    gen = pd.read_parquet(transform.GENERATION_FILE)
    pl = pd.read_parquet(transform.PRICE_LOAD_FILE)
    hours = 24 + 25 + 24

    assert len(pl) == hours
    assert len(gen) == hours * 2  # two generation sources in long format
    assert set(gen["source"]) == {"solar", "wind_onshore"}
    assert not gen.duplicated(["timestamp_utc", "source"]).any()
    assert pl["timestamp_utc"].diff().dropna().eq(pd.Timedelta(hours=1)).all()

    # Volumes summed over 4 quarters, price constant per hour -> mean equals each quarter.
    q_load = pd.Series(np.asarray(12_000.0 + np.arange(4 * hours) % 7))
    assert pl["consumption_mwh"].iloc[0] == q_load.iloc[:4].sum()
    assert pl["price_eur_mwh"].iloc[0] == 40.0

    meta = {m["name"]: m for m in json.loads(transform.METADATA_FILE.read_text())}
    assert set(meta) == {s.name for s in TEST_SERIES}
    assert meta[PRICE.name]["effective_15min_from"] is None
    assert meta[LOAD.name]["missing_hours"] == 0

    ref = pd.read_parquet(transform.REFERENCE_FILE)
    assert set(ref["series"]) == {s.name for s in TEST_SERIES}
