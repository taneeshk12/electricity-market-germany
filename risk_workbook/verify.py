"""Recalculate the workbook in LibreOffice and check every formula against the pandas reference.

openpyxl writes formulas but cannot evaluate them, so this script converts a copy of the
workbook with headless LibreOffice (which recalculates on load), reads the computed values
back and compares them with `metrics.py`.

The copy is built without the What-If Data Tables: LibreOffice emulates them with
MULTIPLE.OPERATIONS and, while doing so, writes into the model's input cells, which corrupts
the scenario results. The Data Table grids are instead printed from the reference model so they
can be compared with Excel by eye; the workbook also has a check cell for one grid entry.

Usage:
    python -m risk_workbook.verify [--csv risk_workbook/output/prices_daily.csv]
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from risk_workbook import build_workbook as bw
from risk_workbook import export
from risk_workbook import metrics as m

SOFFICE_CANDIDATES = ["soffice", "libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"]


def find_soffice() -> str:
    for cand in SOFFICE_CANDIDATES:
        path = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if path:
            return path
    raise SystemExit("LibreOffice not found: install it (brew install --cask libreoffice) to verify formulas.")


def recalculate(src: Path, out_dir: Path) -> Path:
    subprocess.run(
        [find_soffice(), "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out_dir), str(src)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return out_dir / src.name


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.count = 0

    def close(self, label: str, got, want, tol: float = 1e-6) -> None:
        self.count += 1
        both_missing = (got in (None, "")) and (want is None or (isinstance(want, float) and math.isnan(want)))
        if both_missing:
            return
        try:
            ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
        except (TypeError, ValueError):
            ok = got == want
        if not ok:
            self.failures.append(f"{label}: workbook={got!r} reference={want!r}")


def expected_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["Change"] = m.price_changes(df["base_price"])
    out["BuyerPnL"] = m.buyer_pnl(out["Change"])
    out["RollVol"] = m.rolling_vol(out["Change"], bw.VOL_WINDOW)
    out["HistVaR"] = m.rolling_var(out["BuyerPnL"], bw.VAR_WINDOW, bw.VAR_CONFIDENCE, "historical")
    out["ParamVaR"] = m.rolling_var(out["BuyerPnL"], bw.VAR_WINDOW, bw.VAR_CONFIDENCE, "parametric")
    for kind in ("Hist", "Param"):
        var = out[f"{kind}VaR"]
        out[f"{kind}Breach"] = (out["BuyerPnL"] < -var).astype(float).where(var.notna())
    return out


def verify(df: pd.DataFrame) -> Checker:
    chk = Checker()
    with tempfile.TemporaryDirectory() as tmp:
        src = bw.build_workbook(df, Path(tmp) / "check.xlsx", data_tables=False)
        wb = load_workbook(recalculate(src, Path(tmp) / "out"), data_only=True)

    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("#"):
                    chk.failures.append(f"{ws.title}!{c.coordinate}: error {c.value}")

    # 1. Per-day columns on the Data sheet, every row.
    exp = expected_frame(df)
    data = wb["Data"]
    for header in exp.columns:
        col = bw.COL[header]
        for i, want in enumerate(exp[header]):
            chk.close(f"Data!{col}{bw.FIRST_ROW + i} {header}", data[f"{col}{bw.FIRST_ROW + i}"].value, want)

    # 2. Returns sheet.
    ch = exp["Change"].dropna()
    r = wb["Returns"]
    for cell, want in {
        "B7": len(ch),
        "B8": ch.mean(),
        "B9": ch.std(ddof=1),
        "B10": ch.std(ddof=1) * math.sqrt(365),
        "B11": ch.min(),
        "B12": ch.max(),
        "B13": ch.skew(),
        "B14": ch.kurt(),
        "B15": exp["RollVol"].iloc[-1],
        "B16": exp["RollVol"].max(),
        "B18": df["base_price"].mean(),
        "B19": int((df["base_price"] < 0).sum()),
    }.items():
        chk.close(f"Returns!{cell}", r[cell].value, want)
    row, total = 8, 0
    while r[f"G{row}"].value not in (None, "Total"):
        lo, hi = r[f"E{row}"].value, r[f"F{row}"].value
        want = int(((ch > lo) & (ch <= hi)).sum())
        total += want
        chk.close(f"Returns!H{row} histogram {r[f'G{row}'].value}", r[f"H{row}"].value, want)
        row += 1
    chk.close("Returns histogram total = observations", total, len(ch))

    # 3. VaR sheet.
    v = wb["VaR"]
    pnl = exp["BuyerPnL"]
    for col, conf in (("B", 0.95), ("C", 0.99), ("D", bw.VAR_CONFIDENCE)):
        chk.close(f"VaR!{col}10 historical {conf}", v[f"{col}10"].value, m.historical_var(pnl, conf))
        chk.close(f"VaR!{col}11 parametric {conf}", v[f"{col}11"].value, m.parametric_var(pnl, conf))
    tail = pnl.dropna().iloc[-bw.VAR_WINDOW :]
    chk.close("VaR!B16 next-day historical", v["B16"].value, m.historical_var(tail, bw.VAR_CONFIDENCE))
    chk.close("VaR!B17 next-day parametric", v["B17"].value, m.parametric_var(tail, bw.VAR_CONFIDENCE))
    for col, kind in (("B", "Hist"), ("C", "Param")):
        bt = m.backtest(pnl, exp[f"{kind}VaR"], bw.VAR_CONFIDENCE)
        for rr, want in {
            23: bt.observations,
            24: bt.breaches,
            25: bt.expected,
            26: bt.breach_rate,
            27: bt.kupiec_lr,
            28: bt.kupiec_p_value,
        }.items():
            chk.close(f"VaR!{col}{rr} {kind} backtest", v[f"{col}{rr}"].value, want)

    # 4. Scenario sheet (inputs at their defaults).
    s = wb["Scenario"]
    sc = _scenario_from_sheet(s)
    for cell, want in {
        "B11": sc.spot_base,
        "B14": sc.spot,
        "B15": sc.hedged_mwh,
        "B20": sc.margin,
        "B21": sc.margin / sc.actual_mwh,
    }.items():
        chk.close(f"Scenario!{cell}", s[cell].value, want)
    return chk


def _scenario_from_sheet(s, shock: float | None = None, actual: float | None = None) -> m.BuyerScenario:
    return m.BuyerScenario(
        forecast_mwh=s["B5"].value,
        actual_mwh=s["B6"].value if actual is None else actual,
        tariff=s["B7"].value,
        hedge_ratio=s["B8"].value,
        forward_price=s["B9"].value,
        spot_base=s["B11"].value,
        price_shock=s["B10"].value if shock is None else shock,
    )


def expected_data_table(df: pd.DataFrame) -> pd.DataFrame:
    """Reference values for Data Table 2 at the default inputs (margin in EUR)."""
    forecast = bw.POSITION_MWH * bw.SCENARIO_DAYS
    spot_base = float(df["base_price"].tail(30).mean())
    shocks = [-0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    vols = [round(forecast * k) for k in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3)]
    grid = {
        v: [
            m.BuyerScenario(forecast, v, round(spot_base + 20), 0.7, round(spot_base), spot_base, sh).margin
            for sh in shocks
        ]
        for v in vols
    }
    return pd.DataFrame(grid, index=[f"{sh:+.0%}" for sh in shocks]).round(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=export.DAILY_CSV)
    args = parser.parse_args(argv)
    df = pd.read_csv(args.csv, parse_dates=["date"])

    chk = verify(df)
    print(f"Checked {chk.count} workbook values against the pandas reference.")
    print("\nData Table 2 reference (margin EUR; compare with Scenario sheet in Excel):")
    print(expected_data_table(df).to_string(float_format=lambda x: f"{x:,.0f}"))
    if chk.failures:
        print(f"\n{len(chk.failures)} FAILURES:")
        print("\n".join(chk.failures[:50]))
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
