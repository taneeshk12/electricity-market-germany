"""Schema, idempotent load, constraints and warehouse checks against a real PostgreSQL."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import exc, text
from sqlalchemy.engine import Engine

from src import load, warehouse_checks
from tests.conftest import AUTUMN, make_processed, set_period


def _apply_schema(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            for path in load.SCHEMA_FILES:
                cur.execute(path.read_text())
        raw.commit()
    finally:
        raw.close()


def _scalar(engine: Engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def _snapshot(engine: Engine, table: str) -> pd.DataFrame:
    """All rows plus xmin (the creating/updating transaction): unchanged xmin = row not rewritten."""
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT xmin::text AS xmin, * FROM {table} ORDER BY 2, 3"), conn)


@pytest.fixture
def loaded(clean_db: Engine, tmp_path, monkeypatch):
    """Run the real load.main() on synthetic parquet files into the throwaway database."""
    set_period(monkeypatch, *AUTUMN)
    gen, pl = make_processed(*AUTUMN)
    files = {"gen": tmp_path / "gen.parquet", "pl": tmp_path / "pl.parquet"}

    def write(g: pd.DataFrame, p: pd.DataFrame) -> None:
        g.to_parquet(files["gen"], index=False)
        p.to_parquet(files["pl"], index=False)

    write(gen, pl)
    monkeypatch.setattr(load, "GENERATION_FILE", files["gen"])
    monkeypatch.setattr(load, "PRICE_LOAD_FILE", files["pl"])
    monkeypatch.setattr(load, "get_engine", lambda: clean_db)
    load.main()
    return clean_db, gen, pl, write


def test_schema_is_idempotent(clean_db: Engine) -> None:
    _apply_schema(clean_db)
    _apply_schema(clean_db)
    assert _scalar(clean_db, "SELECT count(*) FROM dim_hour") == 24
    assert _scalar(clean_db, "SELECT count(*) FROM dim_source") == 12


def test_dim_date_and_holidays(clean_db: Engine, monkeypatch) -> None:
    set_period(monkeypatch, date(2024, 1, 1), date(2024, 12, 31))
    _apply_schema(clean_db)
    raw = clean_db.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("CALL fill_dim_date(%s, %s)", (date(2024, 1, 1), date(2024, 12, 31)))
            cur.execute("CALL fill_dim_date(%s, %s)", (date(2024, 1, 1), date(2024, 12, 31)))  # idempotent
            load.check_holidays(cur)  # raises on mismatch with the Python `holidays` package
        raw.commit()
    finally:
        raw.close()
    assert _scalar(clean_db, "SELECT count(*) FROM dim_date") == 366
    assert _scalar(clean_db, "SELECT holiday_name FROM dim_date WHERE date = '2024-03-29'") == "Good Friday"
    assert _scalar(clean_db, "SELECT weekday FROM dim_date WHERE date = '2024-10-27'") == 7


def test_load_row_counts_and_dst(loaded) -> None:
    engine, gen, pl, _ = loaded
    assert _scalar(engine, "SELECT count(*) FROM dim_datetime") == len(pl) == 24 + 25 + 24
    assert _scalar(engine, "SELECT count(*) FROM fact_price_load") == len(pl)
    assert _scalar(engine, "SELECT count(*) FROM fact_hourly") == len(gen)
    # 25 hours on the fall-back day, with the local 02:00 hour twice (once per UTC offset).
    assert _scalar(engine, "SELECT count(*) FROM dim_datetime WHERE date_key = 20241027") == 25
    assert _scalar(engine, "SELECT count(*) FROM dim_datetime WHERE date_key = 20241027 AND hour_key = 2") == 2


def test_reload_is_idempotent(loaded) -> None:
    engine, *_ = loaded
    before = {t: _snapshot(engine, t) for t in ("dim_datetime", "fact_price_load", "fact_hourly")}
    load.main()
    for table, snap in before.items():
        pd.testing.assert_frame_equal(_snapshot(engine, table), snap, obj=table)  # same rows, not rewritten


def test_reload_updates_changed_and_deletes_stale_rows(loaded) -> None:
    engine, gen, pl, write = loaded
    pl2 = pl.copy()
    pl2.loc[0, "price_eur_mwh"] = -12.5
    gen2 = gen[gen["source"] != "solar"]  # source disappeared upstream -> rows must go
    write(gen2, pl2)
    before = _snapshot(engine, "fact_price_load")
    load.main()
    after = _snapshot(engine, "fact_price_load")

    changed = after["xmin"] != before["xmin"]
    assert changed.sum() == 1  # only the modified hour was rewritten
    assert float(after.loc[changed, "price_eur_mwh"].iloc[0]) == -12.5
    assert _scalar(engine, "SELECT count(*) FROM fact_hourly") == len(gen2)


def test_failed_load_rolls_back_everything(loaded) -> None:
    engine, gen, pl, write = loaded
    before = _snapshot(engine, "fact_hourly")
    bad = gen.copy()
    bad.loc[0, "source"] = "unknown_source"
    write(bad, pl.assign(price_eur_mwh=1.0))  # price change would be applied before the failure
    with pytest.raises(ValueError, match="unknown_source"):
        load.main()
    pd.testing.assert_frame_equal(_snapshot(engine, "fact_hourly"), before)
    assert _scalar(engine, "SELECT count(*) FROM fact_price_load WHERE price_eur_mwh = 1.0") == 0


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        # FK: fact row for an hour that is not in dim_datetime
        ("INSERT INTO fact_hourly VALUES (2099010100, 20241026, 0, 1, 1.0)", "foreign key"),
        # FK: unknown source
        (
            "INSERT INTO fact_hourly SELECT timestamp_key, date_key, hour_key, 99, 1.0 FROM dim_datetime LIMIT 1",
            "foreign key",
        ),
        # PK: same hour and source twice
        (
            "INSERT INTO fact_hourly "
            "SELECT timestamp_key, date_key, hour_key, source_key, 1.0 FROM fact_hourly LIMIT 1",
            "duplicate key",
        ),
        # CHECK: negative generation
        ("UPDATE fact_hourly SET generation_mwh = -1 WHERE ctid = (SELECT min(ctid) FROM fact_hourly)", "check"),
        # CHECK: only CET/CEST offsets
        ("UPDATE dim_datetime SET utc_offset_h = 3 WHERE ctid = (SELECT min(ctid) FROM dim_datetime)", "check"),
    ],
)
def test_constraints_reject_bad_rows(loaded, sql: str, error: str) -> None:
    engine, *_ = loaded
    with pytest.raises(exc.IntegrityError, match=f"(?i){error}"), engine.begin() as conn:
        conn.execute(text(sql))


def test_v_hourly_residual_load(loaded) -> None:
    engine, *_ = loaded
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT consumption_mwh, variable_renewable_mwh, residual_load_mwh, renewable_share "
                "FROM v_hourly ORDER BY timestamp_key LIMIT 1"
            )
        ).one()
    assert row.residual_load_mwh == row.consumption_mwh - row.variable_renewable_mwh
    assert row.renewable_share == 1  # synthetic data has only solar + wind


def test_warehouse_checks_pass_then_detect_damage(loaded) -> None:
    engine, gen, pl, _ = loaded
    rep = warehouse_checks.run_checks(engine, gen, pl)
    assert rep.critical == [], rep.critical

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM fact_price_load WHERE timestamp_key = (SELECT min(timestamp_key) FROM fact_price_load)")
        )
    rep = warehouse_checks.run_checks(engine, gen, pl)
    failed = {r.name for r in rep.results if r.status == "fail"}
    assert {"row_count.fact_price_load", "hours_without_price_load"} <= failed


def test_warehouse_checks_are_read_only(loaded) -> None:
    engine, gen, pl, _ = loaded
    before = _snapshot(engine, "fact_hourly")
    warehouse_checks.run_checks(engine, gen, pl)
    pd.testing.assert_frame_equal(_snapshot(engine, "fact_hourly"), before)
