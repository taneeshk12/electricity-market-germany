"""Risk workbook: structure of the generated .xlsx and the CSV contract with the VBA macro."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.formula import DataTableFormula

from risk_workbook import build_workbook as bw
from risk_workbook import export, verify

VBA = Path(bw.__file__).parent / "vba" / "RiskDashboard.bas"


def _daily(n: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    base = 80 + np.cumsum(rng.normal(0, 10, n))
    df = pd.DataFrame(
        {
            "date": dates,
            "year": dates.year,
            "month": dates.month,
            "weekday": dates.day_name(),
            "day_type": np.where(dates.weekday >= 5, "Weekend", "Weekday"),
            "base_price": base,
            "peak_price": np.where(dates.weekday >= 5, np.nan, base + 5),
            "min_price": base - 30,
            "max_price": base + 40,
            "negative_hours": 0,
            "load_gwh": 1200.0,
            "renewable_share": 0.55,
        }
    )
    return export._tidy(df)


@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    path = bw.build_workbook(_daily(), tmp_path_factory.mktemp("wb") / "risk.xlsx")
    return load_workbook(path)


def test_sheets_in_presentation_order(workbook) -> None:
    assert workbook.sheetnames == ["Dashboard", "README", "Returns", "VaR", "Scenario", "Data"]


def test_data_names_cover_every_data_row(workbook) -> None:
    last = bw.FIRST_ROW + 320 - 1
    for name, header in bw.DATA_NAMES.items():
        col = bw.COL[header]
        assert workbook.defined_names[name].attr_text == f"'Data'!${col}${bw.FIRST_ROW}:${col}${last}"
    assert workbook["Data"].tables["tblDaily"].ref.endswith(str(last))


def test_newer_excel_functions_carry_the_xlfn_prefix(workbook) -> None:
    # Without the prefix Excel shows #NAME? for functions added after Excel 2007.
    bare = re.compile(r"(?<![._A-Z])(STDEV\.S|PERCENTILE\.INC|NORM\.S\.INV|NORM\.DIST|CHISQ\.DIST\.RT)\(")
    for ws in workbook:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    assert not bare.search(c.value), f"{ws.title}!{c.coordinate}: {c.value}"


def test_scenario_has_one_and_two_variable_data_tables(workbook) -> None:
    ws = workbook["Scenario"]
    tables = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, DataTableFormula)]
    assert len(tables) == 2
    one, two = tables
    assert (one.r1, bool(one.dt2D)) == ("B10", False)  # column input = price shock
    assert (two.r1, two.r2, bool(two.dt2D)) == ("B6", "B10", True)  # row = volume, column = shock
    assert ws["A10"].value == "Price shock to spot" and ws["A6"].value == "Actual volume (MWh)"


def test_inputs_are_named(workbook) -> None:
    for name in ("Vol_Window", "VaR_Conf", "VaR_Window", "Pos_MWh", "Sc_Shock", "Sc_Actual", "LastRefresh"):
        assert name in workbook.defined_names


def test_build_without_data_tables(tmp_path) -> None:
    wb = load_workbook(bw.build_workbook(_daily(), tmp_path / "x.xlsx", data_tables=False))
    assert not any(isinstance(c.value, DataTableFormula) for row in wb["Scenario"].iter_rows() for c in row)


def test_too_little_history_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least"):
        bw.build_workbook(_daily(100), tmp_path / "x.xlsx")


def test_csv_header_matches_vba_import() -> None:
    match = re.search(r'CSV_HEADER As String = "([^"]+)"', VBA.read_text())
    assert match and match.group(1).split(",") == export.DAILY_COLUMNS


def test_vba_names_match_workbook_names() -> None:
    text = VBA.read_text()
    for name, header in bw.DATA_NAMES.items():
        assert f'"{name}"' in text and f'"{header}"' in text


def test_vba_module_uses_crlf() -> None:
    raw = VBA.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_csv_roundtrip(tmp_path) -> None:
    df = _daily(5)
    path = export.write_csv(df, tmp_path / "p.csv")
    assert path.read_text().splitlines()[0] == ",".join(export.DAILY_COLUMNS)
    back = pd.read_csv(path, parse_dates=["date"])
    pd.testing.assert_frame_equal(back, df, check_dtype=False)


@pytest.mark.skipif(
    not any(shutil.which(c) for c in ("soffice", "libreoffice")) and not Path(verify.SOFFICE_CANDIDATES[-1]).exists(),
    reason="LibreOffice not installed",
)
def test_formulas_match_reference_after_recalculation() -> None:
    chk = verify.verify(_daily())
    assert chk.failures == []
    assert chk.count > 2000
