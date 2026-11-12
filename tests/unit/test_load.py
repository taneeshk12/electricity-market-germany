"""Load: key derivation and frame builders (pure functions, no database)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import load
from tests.conftest import AUTUMN, make_processed


@pytest.fixture
def frames(autumn_period):
    return make_processed(*AUTUMN)


def test_timestamp_key_is_utc_hour() -> None:
    ts = pd.Series(pd.to_datetime(["2024-10-27 00:00", "2024-10-27 01:00"], utc=True))
    assert load._timestamp_key(ts).tolist() == [2024102700, 2024102701]


def test_keys_on_repeated_autumn_hour(frames) -> None:
    _, pl = frames
    keyed = load._add_keys(pl)
    repeated = keyed[keyed["timestamp_local"] == pd.Timestamp("2024-10-27 02:00")]
    # Same local date/hour twice, but two distinct UTC keys -> PK stays unique.
    assert len(repeated) == 2
    assert repeated["timestamp_key"].tolist() == [2024102700, 2024102701]
    assert set(repeated["date_key"]) == {20241027} and set(repeated["hour_key"]) == {2}
    assert keyed["timestamp_key"].is_unique


def test_date_key_uses_local_date(frames) -> None:
    _, pl = frames
    keyed = load._add_keys(pl)
    first = keyed.iloc[0]  # 2024-10-25 22:00 UTC = 2024-10-26 00:00 local (CEST)
    assert first["timestamp_key"] == 2024102522
    assert first["date_key"] == 20241026 and first["hour_key"] == 0


def test_build_dim_datetime_peak_flag(frames) -> None:
    _, pl = frames
    dim = load.build_dim_datetime(pl)
    assert list(dim.columns) == [
        "timestamp_key",
        "timestamp_utc",
        "timestamp_local",
        "utc_offset_h",
        "date_key",
        "hour_key",
        "is_peak",
    ]
    # 2024-10-26 is a Saturday, 10-27 a Sunday: no peak hours at all.
    assert not dim.loc[dim["date_key"] < 20241028, "is_peak"].any()
    monday = dim[dim["date_key"] == 20241028].set_index("hour_key")["is_peak"]
    assert monday.loc[8] and monday.loc[19]
    assert not monday.loc[7] and not monday.loc[20]
    assert monday.sum() == 12


def test_build_fact_price_load_keeps_nulls_and_rounds(frames) -> None:
    _, pl = frames
    pl = pl.copy()
    pl.loc[0, "price_eur_mwh"] = np.nan
    pl.loc[1, "price_eur_mwh"] = 12.345678
    pl.loc[1, "consumption_mwh"] = 50_000.12345
    fact = load.build_fact_price_load(pl)
    assert len(fact) == len(pl)
    assert pd.isna(fact.loc[0, "price_eur_mwh"])
    assert fact.loc[1, "price_eur_mwh"] == 12.3457
    assert fact.loc[1, "consumption_mwh"] == 50_000.123


def test_build_fact_hourly_drops_rows_without_value(frames) -> None:
    gen, _ = frames
    gen = gen.copy()
    gen.loc[gen.index[:5], "generation_mwh"] = np.nan
    fact = load.build_fact_hourly(gen, {"solar": 3, "wind_onshore": 1})
    assert len(fact) == len(gen) - 5
    assert fact["generation_mwh"].notna().all()
    assert set(fact["source_key"]) == {1, 3}
    assert not fact.duplicated(["timestamp_key", "source_key"]).any()


def test_build_fact_hourly_rejects_unknown_source(frames) -> None:
    gen, _ = frames
    with pytest.raises(ValueError, match="wind_onshore"):
        load.build_fact_hourly(gen, {"solar": 3})
