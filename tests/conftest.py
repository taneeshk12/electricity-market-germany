"""Shared fixtures: tiny synthetic SMARD data, never the real dataset or database."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import config, extract, transform

# Fall-back DST day 2024-10-27 (25 h) and spring-forward day 2024-03-31 (23 h).
AUTUMN = (date(2024, 10, 26), date(2024, 10, 28))
SPRING = (date(2024, 3, 30), date(2024, 4, 1))

PRICE = config.SmardSeries(4169, "day_ahead_price", "price", "EUR/MWh")
LOAD = config.SmardSeries(410, "grid_load", "consumption", "MWh")
SOLAR = config.SmardSeries(4068, "solar", "generation", "MWh")
WIND = config.SmardSeries(4067, "wind_onshore", "generation", "MWh")
TEST_SERIES = (WIND, SOLAR, LOAD, PRICE)


def set_period(monkeypatch: pytest.MonkeyPatch, start: date, end: date) -> None:
    """Point the pipeline's analysis period at a small window."""
    monkeypatch.setattr(config, "START_DATE", start)
    monkeypatch.setattr(config, "END_DATE", end)


@pytest.fixture
def autumn_period(monkeypatch: pytest.MonkeyPatch) -> tuple[date, date]:
    set_period(monkeypatch, *AUTUMN)
    return AUTUMN


@pytest.fixture
def spring_period(monkeypatch: pytest.MonkeyPatch) -> tuple[date, date]:
    set_period(monkeypatch, *SPRING)
    return SPRING


@pytest.fixture
def raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect raw-chunk storage to a temp dir."""
    path = tmp_path / "raw" / "smard"
    monkeypatch.setattr(extract, "RAW_SMARD_DIR", path)
    return path


@pytest.fixture
def processed_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect processed parquet outputs to a temp dir."""
    path = tmp_path / "processed"
    path.mkdir()
    monkeypatch.setattr(config, "PROCESSED_DIR", path)
    for attr, name in [
        ("GENERATION_FILE", "generation_hourly.parquet"),
        ("PRICE_LOAD_FILE", "price_load_hourly.parquet"),
        ("REFERENCE_FILE", "smard_hourly_reference.parquet"),
        ("METADATA_FILE", "transform_metadata.json"),
    ]:
        monkeypatch.setattr(transform, attr, path / name)
    return path


def quarter_index(start: date, end: date) -> pd.DatetimeIndex:
    """All UTC quarter-hours of a local-date period (end inclusive)."""
    s, e = _bounds(start, end)
    return pd.date_range(s, e, freq="15min", inclusive="left", tz="UTC")


def _bounds(start: date, end: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    s = pd.Timestamp(start, tz=config.LOCAL_TZ).tz_convert("UTC")
    e = (pd.Timestamp(end, tz=config.LOCAL_TZ) + pd.Timedelta(days=1)).tz_convert("UTC")
    return s, e


def series_values(name: str, n: int) -> np.ndarray:
    """Deterministic, plausible values per series."""
    i = np.arange(n)
    if name == "day_ahead_price":
        return np.repeat(np.arange(n // 4 + 1) % 50 + 40.0, 4)[:n]  # constant within an hour
    if name == "grid_load":
        return 12_000.0 + (i % 7)  # ~48 GW per hour
    return 1_000.0 + (i % 5)


@pytest.fixture
def write_chunks(raw_dir: Path) -> Callable[..., None]:
    """Write synthetic raw chunks in SMARD's chart-data JSON format."""

    def _write(
        series: config.SmardSeries, resolution: str, points: list[tuple[int, object]], chunk_ms: int = 0
    ) -> None:
        target = extract.chunk_dir(series, resolution)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{chunk_ms}.json").write_text(json.dumps({"series": [list(p) for p in points]}))

    return _write


def to_ms(ts: pd.DatetimeIndex) -> list[int]:
    return [int(t.value // 1_000_000) for t in ts]


@pytest.fixture
def synthetic_raw(write_chunks, monkeypatch: pytest.MonkeyPatch, autumn_period) -> None:
    """Complete quarter-hour + hourly raw data for TEST_SERIES over the autumn period."""
    monkeypatch.setattr(config, "SMARD_SERIES", TEST_SERIES)
    q = quarter_index(*autumn_period)
    for s in TEST_SERIES:
        values = series_values(s.name, len(q))
        write_chunks(s, "quarterhour", list(zip(to_ms(q), values.tolist(), strict=True)))
        hourly = pd.Series(values, index=q).groupby(q.floor("h"))
        hourly = hourly.mean() if s.kind == "price" else hourly.sum()
        write_chunks(s, "hour", list(zip(to_ms(hourly.index), hourly.tolist(), strict=True)))


def make_processed(
    start: date, end: date, sources: tuple[str, ...] = ("solar", "wind_onshore")
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean processed frames shaped exactly like transform's parquet output."""
    s, e = _bounds(start, end)
    grid = pd.date_range(s, e, freq="h", inclusive="left", tz="UTC", name="timestamp_utc")
    n = len(grid)
    pl = pd.DataFrame(
        {
            "timestamp_utc": grid,
            "price_eur_mwh": (np.arange(n) % 50 + 40.0),
            "consumption_mwh": 48_000.0 + np.arange(n) % 7,
        }
    )
    pl = transform.add_local_time(pl)
    gen = pd.DataFrame(
        [(t, src, 4_000.0 + i % 5) for i, t in enumerate(grid) for src in sources],
        columns=["timestamp_utc", "source", "generation_mwh"],
    )
    gen = transform.add_local_time(gen)
    return gen, pl


def reference_from(gen: pd.DataFrame, pl: pd.DataFrame) -> pd.DataFrame:
    """A SMARD-hourly reference frame that matches the processed frames exactly."""
    ref_gen = gen.rename(columns={"source": "series", "generation_mwh": "value"})[["timestamp_utc", "series", "value"]]
    ref_pl = pl.melt(
        id_vars="timestamp_utc", value_vars=["price_eur_mwh", "consumption_mwh"], var_name="series", value_name="value"
    )
    ref_pl["series"] = ref_pl["series"].map({"price_eur_mwh": "day_ahead_price", "consumption_mwh": "grid_load"})
    return pd.concat([ref_gen, ref_pl], ignore_index=True)


def meta_for(names: list[str]) -> list[dict]:
    return [
        dict(
            name=n,
            raw_points=100,
            duplicate_timestamps=0,
            conflicting_duplicates=0,
            non_numeric_values=0,
            null_quarters=0,
            step_minutes=15.0,
            effective_15min_from=None,
            incomplete_hours=0,
            missing_hours=0,
        )
        for n in names
    ]
