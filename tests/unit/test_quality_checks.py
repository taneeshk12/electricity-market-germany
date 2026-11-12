"""Quality checks: clean data passes; each kind of corruption is detected with the right severity."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import quality_checks as qc
from tests.conftest import AUTUMN, make_processed, meta_for, reference_from


@pytest.fixture
def clean(autumn_period):
    gen, pl = make_processed(*AUTUMN)
    return gen, pl, reference_from(gen, pl), meta_for(["solar", "wind_onshore", "grid_load", "day_ahead_price"])


def _statuses(rep: qc.Report) -> dict[str, str]:
    return {r.name: r.status for r in rep.results}


def test_clean_data_passes_all_checks(clean) -> None:
    rep = qc.run_checks(*clean)
    assert rep.critical == [] and rep.warnings == []
    assert rep.status == "passed"
    assert set(_statuses(rep).values()) == {"pass"}


def test_results_are_machine_readable(clean) -> None:
    rep = qc.run_checks(*clean)
    names = [r.name for r in rep.results]
    assert len(names) == len(set(names)), "check names must be unique"
    for r in rep.results:
        assert r.name and r.description and r.expected and r.actual
        assert r.status in {"pass", "warn", "fail"} and r.severity in {"critical", "warning"}
        assert r.checked_at_utc.endswith("+00:00")
    for required in [
        "price_load_row_count",
        "generation_row_count",
        "null_keys",
        "hourly_continuity",
        "expected_frequency",
        "dst_days",
        "duplicate_keys",
        "price_limits",
        "smard_reconciliation",
        "load_range",
        "negative_generation",
    ]:
        assert required in names


def test_duplicate_row_is_critical(clean) -> None:
    gen, pl, ref, meta = clean
    rep = qc.run_checks(gen, pd.concat([pl, pl.iloc[[5]]]).sort_values("timestamp_utc"), ref, meta)
    s = _statuses(rep)
    assert s["duplicate_keys"] == "fail"
    assert s["monotonic_timestamps"] == "fail"
    assert "Duplicate keys found" in rep.critical


def test_conflicting_raw_duplicates_are_critical(clean) -> None:
    gen, pl, ref, meta = clean
    meta[0]["conflicting_duplicates"] = 3
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["conflicting_raw_duplicates"] == "fail"


def test_missing_hour_breaks_grid(clean) -> None:
    gen, pl, ref, meta = clean
    pl = pl.drop(index=10).reset_index(drop=True)
    s = _statuses(qc.run_checks(gen, pl, ref, meta))
    assert s["price_load_row_count"] == "fail"
    assert s["hourly_continuity"] == "fail"
    assert s["dst_days"] == "fail"  # a normal day now has 23 hours


def test_off_grid_timestamp_is_detected(clean) -> None:
    gen, pl, ref, meta = clean
    pl.loc[3, "timestamp_utc"] += pd.Timedelta(minutes=15)
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["expected_frequency"] == "fail"


def test_null_key_is_critical(clean) -> None:
    gen, pl, ref, meta = clean
    gen.loc[0, "source"] = None
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["null_keys"] == "fail"


def test_dst_days_pass_on_real_switch_days(clean) -> None:
    rep = qc.run_checks(*clean)
    dst = next(r for r in rep.results if r.name == "dst_days")
    assert dst.status == "pass"
    assert "1 irregular days" in dst.actual  # 2024-10-27 has 25 hours


def test_missing_generation_is_warning_but_missing_price_is_critical(clean) -> None:
    gen, pl, ref, meta = clean
    gen.loc[gen.index[:3], "generation_mwh"] = np.nan
    pl.loc[0, "price_eur_mwh"] = np.nan
    ref = reference_from(gen, pl)
    rep = qc.run_checks(gen, pl, ref, meta)
    s = _statuses(rep)
    assert s["missing_hours.solar"] == "warn" and s["missing_hours.wind_onshore"] == "warn"
    assert s["missing_hours.price_eur_mwh"] == "fail"
    assert any("price_eur_mwh" in c for c in rep.critical)


def test_nuclear_gaps_are_expected_not_flagged(clean) -> None:
    gen, pl, ref, meta = clean
    nuc = gen[gen["source"] == "solar"].assign(source="nuclear", generation_mwh=np.nan)
    gen = pd.concat([gen, nuc], ignore_index=True)
    s = _statuses(qc.run_checks(gen, pl, ref, meta))
    assert "missing_hours.nuclear" not in s


def test_price_outside_market_limits_is_critical(clean) -> None:
    gen, pl, ref, meta = clean
    pl.loc[7, "price_eur_mwh"] = 4_500.0
    ref = reference_from(gen, pl)
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["price_limits"] == "fail"


def test_negative_price_within_limits_is_fine(clean) -> None:
    gen, pl, ref, meta = clean
    pl.loc[7, "price_eur_mwh"] = -135.45
    ref = reference_from(gen, pl)
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["price_limits"] == "pass"


def test_negative_generation_is_warning(clean) -> None:
    gen, pl, ref, meta = clean
    gen.loc[0, "generation_mwh"] = -1.0
    rep = qc.run_checks(gen, pl, reference_from(gen, pl), meta)
    assert _statuses(rep)["negative_generation"] == "warn"
    assert rep.critical == []


def test_load_in_wrong_unit_is_flagged(clean) -> None:
    gen, pl, ref, meta = clean
    pl["consumption_mwh"] = pl["consumption_mwh"] / 4  # quarter-hour values mistaken for hourly
    rep = qc.run_checks(gen, pl, reference_from(gen, pl), meta)
    assert _statuses(rep)["load_range"] == "warn"


def test_reconciliation_detects_aggregation_error_beyond_tolerance(clean) -> None:
    gen, pl, ref, meta = clean
    ref = ref.copy()
    idx = ref.index[ref["series"] == "grid_load"][0]
    ref.loc[idx, "value"] += qc.TOL_VOLUME_MWH * 0.5  # rounding noise -> ok
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["smard_reconciliation"] == "pass"
    ref.loc[idx, "value"] += 5.0
    assert _statuses(qc.run_checks(gen, pl, ref, meta))["smard_reconciliation"] == "fail"


def test_write_reports_produces_markdown_and_json(clean, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(qc.config, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(qc, "REPORT_FILE", tmp_path / "r.md")
    monkeypatch.setattr(qc, "REPORT_JSON", tmp_path / "r.json")
    gen, pl, ref, meta = clean
    gen.loc[0, "generation_mwh"] = -1.0
    rep = qc.run_checks(gen, pl, reference_from(gen, pl), meta)
    manifest = {"source": "test", "region": "DE-LU", "retrieved_at_utc": "x", "period": ["a", "b"]}
    qc.write_reports(rep, manifest)

    data = json.loads((tmp_path / "r.json").read_text())
    assert data["status"] == "passed_with_warnings"
    assert data["summary"]["warn"] == 1 and data["summary"]["fail"] == 0
    assert {"name", "description", "expected", "actual", "status", "checked_at_utc"} <= set(data["checks"][0])
    md = (tmp_path / "r.md").read_text()
    assert "## Check summary" in md and "⚠️ warn" in md


def test_main_exits_non_zero_on_critical(monkeypatch) -> None:
    rep = qc.Report()
    rep.record("x", "d", 0, 1, False)
    monkeypatch.setattr(qc, "run", lambda: rep)
    with pytest.raises(SystemExit, match="Critical data quality issues"):
        qc.main()
