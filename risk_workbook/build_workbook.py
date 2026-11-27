"""Build the Power Price Risk Workbook (.xlsx) from the daily price export.

Every risk number in the workbook is a live Excel formula, not a value pasted from Python,
so a reviewer can click any cell and follow the logic. `metrics.py` holds the same maths in
pandas, and `verify.py` checks one against the other.

Formulas refer to the data through workbook names (d_Base, d_PnL, ...), not structured table
references, because LibreOffice, which `verify.py` uses to recalculate, cannot evaluate table
references. The VBA refresh macro resizes those names when new data is imported.

Usage:
    python -m risk_workbook.build_workbook                  # export from warehouse, then build
    python -m risk_workbook.build_workbook --csv FILE       # build from an existing export
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.axis import ChartLines
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.formula import DataTableFormula
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from risk_workbook import export
from src.config import setup_logging

log = logging.getLogger(__name__)

WORKBOOK_PATH: Path = export.OUTPUT_DIR / "Power_Price_Risk_Workbook.xlsx"

# --- Defaults (all editable in the workbook; yellow cells) -------------------------------------
VOL_WINDOW = 30  # days in the rolling volatility
VAR_CONFIDENCE = 0.99  # confidence level used by the rolling backtest
VAR_WINDOW = 250  # look-back days for each day's VaR (about one trading year)
POSITION_MWH = 1_000  # MWh bought per day by the hypothetical buyer (~42 MW baseload)
SCENARIO_DAYS = 30  # length of the supply period in the scenario sheet
HIST_BIN_WIDTH = 10  # EUR/MWh
HIST_BIN_LIMIT = 100  # inner bins span -100..+100; two tail bins catch the rest

# --- Data sheet layout -------------------------------------------------------------------------
HEADER_ROW = 4
FIRST_ROW = HEADER_ROW + 1

# (header, export column or None for a formula column, number format)
DATA_COLUMNS: list[tuple[str, str | None, str]] = [
    ("Date", "date", "yyyy-mm-dd"),
    ("Year", "year", "0"),
    ("Month", "month", "0"),
    ("Weekday", "weekday", "@"),
    ("DayType", "day_type", "@"),
    ("BasePrice", "base_price", "#,##0.00"),
    ("PeakPrice", "peak_price", "#,##0.00"),
    ("MinPrice", "min_price", "#,##0.00"),
    ("MaxPrice", "max_price", "#,##0.00"),
    ("NegHours", "negative_hours", "0"),
    ("LoadGWh", "load_gwh", "#,##0.0"),
    ("RenShare", "renewable_share", "0.0%"),
    ("Obs", None, "0"),
    ("Change", None, "#,##0.00;[Red]-#,##0.00"),
    ("BuyerPnL", None, "#,##0.00;[Red]-#,##0.00"),
    ("RollVol", None, "#,##0.00"),
    ("HistVaR", None, "#,##0.00"),
    ("ParamVaR", None, "#,##0.00"),
    ("HistBreach", None, "0"),
    ("ParamBreach", None, "0"),
]
COL = {name: get_column_letter(i + 1) for i, (name, _, _) in enumerate(DATA_COLUMNS)}

# Workbook names over whole data columns; the refresh macro rewrites these after an import.
DATA_NAMES: dict[str, str] = {
    "d_Date": "Date",
    "d_Year": "Year",
    "d_Month": "Month",
    "d_Base": "BasePrice",
    "d_NegHours": "NegHours",
    "d_Change": "Change",
    "d_PnL": "BuyerPnL",
    "d_RollVol": "RollVol",
    "d_HistVaR": "HistVaR",
    "d_ParamVaR": "ParamVaR",
    "d_HistBreach": "HistBreach",
    "d_ParamBreach": "ParamBreach",
}

# --- Styles ------------------------------------------------------------------------------------
NAVY = "1F3864"
F_TITLE = Font(bold=True, size=16, color=NAVY)
F_H2 = Font(bold=True, size=12, color=NAVY)
F_HEADER = Font(bold=True, color="FFFFFF")
F_INPUT = Font(color="0000FF")  # finance convention: blue = hard-coded input
F_NOTE = Font(italic=True, color="595959", size=9)
F_KPI = Font(bold=True, size=18, color=NAVY)
FILL_HEADER = PatternFill("solid", fgColor=NAVY)
FILL_INPUT = PatternFill("solid", fgColor="FFF2CC")
FILL_KPI = PatternFill("solid", fgColor="EAF1FB")
FILL_GROUP = {"raw": "D9D9D9", "returns": "DDEBF7", "var": "FCE4D6"}
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _name(wb: Workbook, name: str, ref: str) -> None:
    wb.defined_names[name] = DefinedName(name, attr_text=ref)


def _abs(sheet: str, cell: str) -> str:
    col = "".join(c for c in cell if c.isalpha())
    row = "".join(c for c in cell if c.isdigit())
    return f"'{sheet}'!${col}${row}"


def _input(ws: Worksheet, cell: str, value, fmt: str, wb: Workbook | None = None, name: str | None = None) -> None:
    c = ws[cell]
    c.value = value
    c.font, c.fill, c.border, c.number_format = F_INPUT, FILL_INPUT, BOX, fmt
    if wb is not None and name:
        _name(wb, name, _abs(ws.title, cell))


def _label_rows(ws: Worksheet, start_row: int, rows: list[tuple], label_col: str = "A", value_col: str = "B") -> None:
    """Write (label, formula, number format[, note]) rows."""
    for i, row in enumerate(rows):
        r = start_row + i
        label, formula, fmt = row[:3]
        ws[f"{label_col}{r}"] = label
        cell = ws[f"{value_col}{r}"]
        cell.value, cell.number_format, cell.border = formula, fmt, BOX
        if len(row) > 3:
            note_col = get_column_letter(ws[f"{value_col}{r}"].column + 1)
            ws[f"{note_col}{r}"] = row[3]
            ws[f"{note_col}{r}"].font = F_NOTE


def _header(ws: Worksheet, row: int, col: int, labels: list[str]) -> None:
    for j, text in enumerate(labels):
        c = ws.cell(row=row, column=col + j, value=text)
        c.font, c.fill, c.alignment = F_HEADER, FILL_HEADER, Alignment(horizontal="center", wrap_text=True)


def _widths(ws: Worksheet, widths: dict[str, float]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def _show_axes(chart) -> None:
    # Newer Excel builds hide axes that openpyxl leaves at the default delete=None.
    chart.x_axis.delete = False
    chart.y_axis.delete = False


# --- Sheets ------------------------------------------------------------------------------------
def build_data(wb: Workbook, df: pd.DataFrame) -> int:
    ws = wb.create_sheet("Data")
    n = len(df)
    last = FIRST_ROW + n - 1
    ws["A1"] = "Daily DE-LU day-ahead prices and per-day risk columns"
    ws["A1"].font = F_H2
    ws["A2"] = (
        "Grey: exported from the PostgreSQL warehouse (EUR/MWh, local days). Blue: returns and volatility. "
        "Orange: out-of-sample VaR backtest. Formula columns refer to the inputs on the Returns and VaR sheets."
    )
    ws["A2"].font = F_NOTE

    for j, (header, _, _) in enumerate(DATA_COLUMNS, start=1):
        c = ws.cell(row=HEADER_ROW, column=j, value=header)
        c.font = Font(bold=True)
    for i, rec in enumerate(df.itertuples(index=False), start=FIRST_ROW):
        values = rec._asdict()
        for j, (_, src, fmt) in enumerate(DATA_COLUMNS, start=1):
            if src is None:
                continue
            v = values[src]
            if pd.isna(v):
                v = None
            elif src == "date":
                v = v.to_pydatetime()
            c = ws.cell(row=i, column=j, value=v)
            c.number_format = fmt

    c = COL
    for r in range(FIRST_ROW, last + 1):
        past = f"INDEX({c['BuyerPnL']}:{c['BuyerPnL']},ROW()-VaR_Window):INDEX({c['BuyerPnL']}:{c['BuyerPnL']},ROW()-1)"
        formulas = {
            "Obs": f"=ROW()-{HEADER_ROW}",
            "Change": f'=IF({c["Obs"]}{r}=1,"",{c["BasePrice"]}{r}-{c["BasePrice"]}{r - 1})',
            "BuyerPnL": f'=IF({c["Change"]}{r}="","",-{c["Change"]}{r})',
            "RollVol": (
                f'=IF({c["Obs"]}{r}<=Vol_Window,"",'
                f"_xlfn.STDEV.S(INDEX({c['Change']}:{c['Change']},ROW()-Vol_Window+1):{c['Change']}{r}))"
            ),
            "HistVaR": f'=IF({c["Obs"]}{r}<=VaR_Window+1,"",-_xlfn.PERCENTILE.INC({past},1-VaR_Conf))',
            "ParamVaR": (
                f'=IF({c["Obs"]}{r}<=VaR_Window+1,"",'
                f"-(AVERAGE({past})+_xlfn.NORM.S.INV(1-VaR_Conf)*_xlfn.STDEV.S({past})))"
            ),
            "HistBreach": f'=IF({c["HistVaR"]}{r}="","",IF({c["BuyerPnL"]}{r}<-{c["HistVaR"]}{r},1,0))',
            "ParamBreach": f'=IF({c["ParamVaR"]}{r}="","",IF({c["BuyerPnL"]}{r}<-{c["ParamVaR"]}{r},1,0))',
        }
        for header, formula in formulas.items():
            cell = ws[f"{c[header]}{r}"]
            cell.value = formula
            cell.number_format = next(f for h, _, f in DATA_COLUMNS if h == header)

    table = Table(displayName="tblDaily", ref=f"A{HEADER_ROW}:{get_column_letter(len(DATA_COLUMNS))}{last}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(table)

    groups = {"raw": ("Date", "RenShare"), "returns": ("Obs", "RollVol"), "var": ("HistVaR", "ParamBreach")}
    for group, (first, last_col) in groups.items():
        lo, hi = ws[f"{c[first]}1"].column, ws[f"{c[last_col]}1"].column
        for j in range(lo, hi + 1):
            ws.cell(row=HEADER_ROW, column=j).fill = PatternFill("solid", fgColor=FILL_GROUP[group])

    for name, header in DATA_NAMES.items():
        col = c[header]
        _name(wb, name, f"'Data'!${col}${FIRST_ROW}:${col}${last}")
    ws.freeze_panes = f"B{FIRST_ROW}"
    _widths(ws, {get_column_letter(j): 11 for j in range(1, len(DATA_COLUMNS) + 1)})
    ws.column_dimensions["A"].width = 12
    return last


def build_returns(wb: Workbook, last: int) -> None:
    ws = wb.create_sheet("Returns")
    ws["A1"] = "Returns and volatility"
    ws["A1"].font = F_TITLE
    ws["A2"] = (
        "Risk factor = daily change in the base price (EUR/MWh). Percentage or log returns are not used: "
        "German prices reach zero and go negative, where both are undefined."
    )
    ws["A2"].font = F_NOTE

    ws["A4"] = "Rolling volatility window (days)"
    _input(ws, "B4", VOL_WINDOW, "0", wb, "Vol_Window")

    ws["A6"] = "Daily price changes"
    ws["A6"].font = F_H2
    _label_rows(
        ws,
        7,
        [
            ("Observations", "=COUNT(d_Change)", "#,##0"),
            ("Mean change (EUR/MWh)", "=AVERAGE(d_Change)", "0.00"),
            ("Std deviation, daily (EUR/MWh)", "=_xlfn.STDEV.S(d_Change)", "0.00", "Full-sample daily volatility"),
            ("Std deviation, annualised", "=B9*SQRT(365)", "0.00", "x SQRT(365): power trades every calendar day"),
            ("Largest fall", "=MIN(d_Change)", "0.00"),
            ("Largest rise", "=MAX(d_Change)", "0.00"),
            ("Skewness", "=SKEW(d_Change)", "0.00"),
            ("Excess kurtosis", "=KURT(d_Change)", "0.00", "0 for a normal distribution; >0 = fat tails"),
            ("Latest rolling volatility", "=INDEX(d_RollVol,ROWS(d_RollVol))", "0.00", "Last day in the data"),
            ("Highest rolling volatility", "=MAX(d_RollVol)", "0.00"),
            ("Date of highest", "=INDEX(d_Date,MATCH(B16,d_RollVol,0))", "yyyy-mm-dd"),
            ("Average base price (EUR/MWh)", "=AVERAGE(d_Base)", "0.00"),
            ("Days with a negative base price", '=COUNTIF(d_Base,"<0")', "0"),
        ],
    )
    for name, cell in {"Ret_Mean": "B8", "Ret_SD": "B9", "Ret_N": "B7"}.items():
        _name(wb, name, _abs("Returns", cell))

    # Histogram with a normal overlay: the gap in the tails is why parametric VaR understates risk.
    ws["E6"] = "Histogram of daily changes"
    ws["E6"].font = F_H2
    _header(ws, 7, 5, ["From", "To", "Bin", "Days", "Normal fit", "Share"])
    edges = list(range(-HIST_BIN_LIMIT, HIST_BIN_LIMIT + 1, HIST_BIN_WIDTH))
    bins = [(None, edges[0])] + list(zip(edges[:-1], edges[1:], strict=True)) + [(edges[-1], None)]
    for i, (lo, hi) in enumerate(bins):
        r = 8 + i
        ws[f"E{r}"] = lo if lo is not None else -1e9
        ws[f"F{r}"] = hi if hi is not None else 1e9
        label = f"< {hi}" if lo is None else (f"> {lo}" if hi is None else f"{lo} to {hi}")
        ws[f"G{r}"] = label
        ws[f"H{r}"] = f'=COUNTIFS(d_Change,">"&E{r},d_Change,"<="&F{r})'
        ws[f"I{r}"] = f"=Ret_N*(_xlfn.NORM.DIST(F{r},Ret_Mean,Ret_SD,TRUE)-_xlfn.NORM.DIST(E{r},Ret_Mean,Ret_SD,TRUE))"
        ws[f"J{r}"] = f"=H{r}/Ret_N"
        for col, fmt in {"E": "0;-0;0", "F": "0;-0;0", "H": "0", "I": "0.0", "J": "0.0%"}.items():
            ws[f"{col}{r}"].number_format = fmt
        for col, bound in (("E", lo), ("F", hi)):
            if bound is None:  # open tail bound: keep the value for COUNTIFS, hide it on screen
                ws[f"{col}{r}"].number_format = ";;"

    hist_last = 8 + len(bins) - 1
    ws[f"G{hist_last + 1}"] = "Total"
    ws[f"H{hist_last + 1}"] = f"=SUM(H8:H{hist_last})"
    ws[f"G{hist_last + 1}"].font = ws[f"H{hist_last + 1}"].font = Font(bold=True)
    ws[f"E{hist_last + 2}"] = "Tail bins use +/-1E9 as open bounds."
    ws[f"E{hist_last + 2}"].font = F_NOTE

    bar = BarChart()
    bar.title = "Distribution of daily price changes vs. normal fit"
    bar.y_axis.title = "Days"
    bar.x_axis.title = "Change in base price (EUR/MWh)"
    bar.add_data(Reference(ws, min_col=8, min_row=7, max_row=hist_last), titles_from_data=True)
    bar.set_categories(Reference(ws, min_col=7, min_row=8, max_row=hist_last))
    bar.gapWidth = 10
    line = LineChart()
    line.add_data(Reference(ws, min_col=9, min_row=7, max_row=hist_last), titles_from_data=True)
    line.series[0].smooth = True
    bar += line
    bar.height, bar.width = 9, 18
    _show_axes(bar)
    ws.add_chart(bar, "L6")

    price = LineChart()
    price.title = "Daily base price and rolling volatility"
    price.y_axis.title = "Base price (EUR/MWh)"
    price.add_data(Reference(wb["Data"], min_col=6, min_row=HEADER_ROW, max_row=last), titles_from_data=True)
    price.set_categories(Reference(wb["Data"], min_col=1, min_row=FIRST_ROW, max_row=last))
    price.x_axis.number_format = "mmm yy"
    price.y_axis.majorGridlines = ChartLines()
    vol = LineChart()
    vol_col = ws.parent["Data"][f"{COL['RollVol']}1"].column
    vol.add_data(Reference(wb["Data"], min_col=vol_col, min_row=HEADER_ROW, max_row=last), titles_from_data=True)
    vol.y_axis.axId = 200
    vol.y_axis.title = "Rolling std dev (EUR/MWh)"
    vol.y_axis.crosses = "max"
    vol.y_axis.majorGridlines = None
    price += vol
    for s in price.series:
        s.graphicalProperties.line.width = 12_700
    price.height, price.width = 9, 18
    _show_axes(price)
    vol.y_axis.delete = False
    ws.add_chart(price, "L25")
    _widths(ws, {"A": 34, "B": 13, "C": 40, "E": 8, "F": 8, "G": 12, "H": 8, "I": 10, "J": 8})


def build_var(wb: Workbook, last: int) -> None:
    ws = wb.create_sheet("VaR")
    ws["A1"] = "Value-at-Risk: historical vs. parametric, with backtest"
    ws["A1"].font = F_TITLE
    ws["A2"] = (
        "Position: a buyer that must purchase a fixed volume at the day-ahead price every day, so a price "
        "rise is a loss. VaR = 1-day loss not exceeded with the given confidence, shown as a positive number."
    )
    ws["A2"].font = F_NOTE

    ws["A4"] = "Confidence level (backtest)"
    _input(ws, "B4", VAR_CONFIDENCE, "0.0%", wb, "VaR_Conf")
    ws["A5"] = "Estimation window (days)"
    _input(ws, "B5", VAR_WINDOW, "0", wb, "VaR_Window")
    ws["A6"] = "Position (MWh bought per day)"
    _input(ws, "B6", POSITION_MWH, "#,##0", wb, "Pos_MWh")
    ws["C6"] = "1,000 MWh/day is about a 42 MW baseload customer portfolio"
    ws["C6"].font = F_NOTE

    ws["A8"] = "Full-sample VaR (all days)"
    ws["A8"].font = F_H2
    _header(ws, 9, 1, ["Method", "95%", "99%", "Input level", "Input level, EUR"])
    ws["B9"], ws["C9"] = 0.95, 0.99  # header cells double as the confidence parameters
    ws["B9"].number_format = ws["C9"].number_format = "0%"
    ws["D9"] = '=TEXT(VaR_Conf,"0.0%")'
    methods = {
        "Historical (EUR/MWh)": lambda conf: f"=-_xlfn.PERCENTILE.INC(d_PnL,1-{conf})",
        "Parametric normal (EUR/MWh)": lambda conf: (
            f"=-(AVERAGE(d_PnL)+_xlfn.NORM.S.INV(1-{conf})*_xlfn.STDEV.S(d_PnL))"
        ),
    }
    for i, (label, fn) in enumerate(methods.items()):
        r = 10 + i
        ws[f"A{r}"] = label
        ws[f"B{r}"], ws[f"C{r}"], ws[f"D{r}"] = fn("B$9"), fn("C$9"), fn("VaR_Conf")
        ws[f"E{r}"] = f"=D{r}*Pos_MWh"
        for col in "BCD":
            ws[f"{col}{r}"].number_format = "0.00"
        ws[f"E{r}"].number_format = '#,##0" EUR"'
    ws["A12"] = "Historical / parametric"
    for col in "BCD":
        ws[f"{col}12"] = f"={col}10/{col}11"
        ws[f"{col}12"].number_format = "0.00x"
    ws["A13"] = "Ratio above 1 at 99% = fat tails the normal model misses."
    ws["A13"].font = F_NOTE

    ws["A15"] = "VaR for the next day (last window of data)"
    ws["A15"].font = F_H2
    window = "INDEX(d_PnL,ROWS(d_PnL)-VaR_Window+1):INDEX(d_PnL,ROWS(d_PnL))"
    _label_rows(
        ws,
        16,
        [
            ("Historical, EUR/MWh", f"=-_xlfn.PERCENTILE.INC({window},1-VaR_Conf)", "0.00"),
            (
                "Parametric, EUR/MWh",
                f"=-(AVERAGE({window})+_xlfn.NORM.S.INV(1-VaR_Conf)*_xlfn.STDEV.S({window}))",
                "0.00",
            ),
            ("Historical, EUR on position", "=B16*Pos_MWh", '#,##0" EUR"'),
            ("Parametric, EUR on position", "=B17*Pos_MWh", '#,##0" EUR"'),
        ],
    )
    for name, cell in {"Next_HistVaR": "B16", "Next_ParamVaR": "B17", "Next_HistVaR_EUR": "B18"}.items():
        _name(wb, name, _abs("VaR", cell))

    ws["A21"] = "Backtest: did the loss exceed the VaR set the day before?"
    ws["A21"].font = F_H2
    _header(ws, 22, 1, ["Measure", "Historical", "Parametric"])
    rows = [
        ("Days tested", "=COUNT({b})", "#,##0"),
        ("Breaches", "=SUM({b})", "0"),
        ("Expected breaches", "={c}23*(1-VaR_Conf)", "0.0"),
        ("Breach rate", "={c}24/{c}23", "0.00%"),
        (
            "Kupiec LR statistic",
            "=-2*(({c}23-{c}24)*LN(VaR_Conf)+{c}24*LN(1-VaR_Conf))"
            "+2*(IF({c}24<{c}23,({c}23-{c}24)*LN(1-{c}26),0)+IF({c}24>0,{c}24*LN({c}26),0))",
            "0.00",
        ),
        ("p-value", "=_xlfn.CHISQ.DIST.RT({c}27,1)", "0.000"),
        ("Model at 5% significance", '=IF({c}28<0.05,"Rejected","Not rejected")', "@"),
    ]
    for i, (label, tpl, fmt) in enumerate(rows):
        r = 23 + i
        ws[f"A{r}"] = label
        for col, rng in (("B", "d_HistBreach"), ("C", "d_ParamBreach")):
            ws[f"{col}{r}"] = tpl.format(b=rng, c=col)
            ws[f"{col}{r}"].number_format = fmt
            ws[f"{col}{r}"].border = BOX
    for name, cell in {
        "BT_HistBreaches": "B24",
        "BT_Expected": "B25",
        "BT_HistP": "B28",
        "BT_ParamBreaches": "C24",
        "BT_HistResult": "B29",
        "BT_ParamResult": "C29",
    }.items():
        _name(wb, name, _abs("VaR", cell))
    ws["A30"] = (
        "Each day's VaR uses only the previous VaR_Window days (out of sample). Kupiec's proportion-of-failures "
        "test: is the breach rate consistent with 1 - confidence?"
    )
    ws["A30"].font = F_NOTE

    ws["A32"] = "Breaches by year"
    ws["A32"].font = F_H2
    _header(ws, 33, 1, ["Year", "Days tested", "Hist. breaches", "Param. breaches", "Expected"])
    for i in range(5):
        r = 34 + i
        ws[f"A{r}"] = "=MIN(d_Year)" if i == 0 else f'=IF(A{r - 1}="","",IF(A{r - 1}+1>MAX(d_Year),"",A{r - 1}+1))'
        ws[f"B{r}"] = f'=IF(A{r}="","",COUNTIFS(d_Year,A{r},d_HistBreach,">=0"))'
        ws[f"C{r}"] = f'=IF(A{r}="","",SUMIFS(d_HistBreach,d_Year,A{r}))'
        ws[f"D{r}"] = f'=IF(A{r}="","",SUMIFS(d_ParamBreach,d_Year,A{r}))'
        ws[f"E{r}"] = f'=IF(A{r}="","",B{r}*(1-VaR_Conf))'
        ws[f"E{r}"].number_format = "0.0"

    data = wb["Data"]
    chart = LineChart()
    chart.title = "Backtest: daily loss vs. VaR set the day before (EUR/MWh)"
    for header in ("Change", "HistVaR", "ParamVaR"):
        col = data[f"{COL[header]}1"].column
        chart.add_data(Reference(data, min_col=col, min_row=HEADER_ROW, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(data, min_col=1, min_row=FIRST_ROW, max_row=last))
    chart.x_axis.number_format = "mmm yy"
    chart.y_axis.title = "Loss for a buyer = price rise (EUR/MWh)"
    widths = [9_525, 19_050, 19_050]
    colours = ["A6A6A6", "C00000", "2E75B6"]
    for s, w, colour in zip(chart.series, widths, colours, strict=True):
        s.graphicalProperties.line.width = w
        s.graphicalProperties.line.solidFill = colour
    chart.height, chart.width = 10, 22
    _show_axes(chart)
    ws.add_chart(chart, "G4")
    _widths(ws, {"A": 34, "B": 13, "C": 13, "D": 13, "E": 16})


def build_scenario(wb: Workbook, df: pd.DataFrame, data_tables: bool = True) -> None:
    ws = wb.create_sheet("Scenario")
    ws["A1"] = "Scenario: margin of a hypothetical power buyer"
    ws["A1"].font = F_TITLE
    ws["A2"] = (
        "A supplier sells to customers at a fixed tariff for one month. It bought part of the forecast volume "
        "forward; the rest (or any shortfall) is settled at the day-ahead price, which the shock moves."
    )
    ws["A2"].font = F_NOTE

    spot_base = float(df["base_price"].tail(30).mean())
    forecast = POSITION_MWH * SCENARIO_DAYS
    ws["A4"] = "Inputs"
    ws["A4"].font = F_H2
    inputs = [
        ("Forecast volume (MWh)", forecast, "#,##0", "Sc_Forecast", "Contracted customer demand for the month"),
        ("Actual volume (MWh)", forecast, "#,##0", "Sc_Actual", "Varied in the 2-D Data Table"),
        ("Customer tariff (EUR/MWh)", round(spot_base + 20), "0.00", "Sc_Tariff", "Fixed sale price, set at build"),
        ("Hedge ratio (share of forecast)", 0.7, "0%", "Sc_Hedge", "Bought forward in advance"),
        ("Forward price (EUR/MWh)", round(spot_base), "0.00", "Sc_Forward", "Price paid for the hedged volume"),
        ("Price shock to spot", 0.0, "+0%;-0%;0%", "Sc_Shock", "Varied in both Data Tables"),
    ]
    for i, (label, value, fmt, name, note) in enumerate(inputs):
        r = 5 + i
        ws[f"A{r}"] = label
        _input(ws, f"B{r}", value, fmt, wb, name)
        ws[f"C{r}"] = note
        ws[f"C{r}"].font = F_NOTE
    ws["A11"] = "Spot base price (EUR/MWh)"
    ws["B11"] = "=AVERAGE(INDEX(d_Base,ROWS(d_Base)-29):INDEX(d_Base,ROWS(d_Base)))"
    ws["B11"].number_format = "0.00"
    ws["B11"].border = BOX
    ws["C11"] = "Average base price of the last 30 days in the data (formula)"
    ws["C11"].font = F_NOTE
    _name(wb, "Sc_SpotBase", _abs("Scenario", "B11"))

    ws["A13"] = "Result"
    ws["A13"].font = F_H2
    _label_rows(
        ws,
        14,
        [
            ("Spot price after shock (EUR/MWh)", "=Sc_SpotBase*(1+Sc_Shock)", "0.00"),
            ("Hedged volume (MWh)", "=Sc_Forecast*Sc_Hedge", "#,##0"),
            (
                "Open volume at spot (MWh)",
                "=Sc_Actual-B15",
                "#,##0;[Red]-#,##0",
                "Negative = surplus sold back at spot",
            ),
            ("Cost of hedge (EUR)", "=B15*Sc_Forward", "#,##0"),
            ("Cost of open volume (EUR)", "=B16*B14", "#,##0;[Red]-#,##0"),
            ("Revenue (EUR)", "=Sc_Actual*Sc_Tariff", "#,##0"),
            ("Margin (EUR)", "=B19-B17-B18", "#,##0;[Red]-#,##0"),
            ("Margin (EUR/MWh)", "=IF(Sc_Actual=0,0,B20/Sc_Actual)", "0.00;[Red]-0.00"),
            (
                "Break-even spot price (EUR/MWh)",
                '=IF(B16=0,"n/a",(B19-B17)/B16)',
                "0.00",
                "Spot price at which margin = 0",
            ),
        ],
    )
    ws["B20"].font = Font(bold=True)
    _name(wb, "Sc_Margin", _abs("Scenario", "B20"))
    _name(wb, "Sc_MarginMWh", _abs("Scenario", "B21"))

    # One-variable Data Table: shock down column E, outputs across.
    shocks = [-0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    ws["E4"] = "Data Table 1: margin vs. price shock"
    ws["E4"].font = F_H2
    _header(ws, 5, 5, ["Price shock", "Spot price", "Margin (EUR)", "Margin (EUR/MWh)"])
    ws["E6"] = "(formulas)"
    ws["E6"].font = F_NOTE
    ws["F6"], ws["G6"], ws["H6"] = "=B14", "=Sc_Margin", "=Sc_MarginMWh"
    first, end = 7, 7 + len(shocks) - 1
    for i, s in enumerate(shocks):
        r = first + i
        ws[f"E{r}"] = s
        ws[f"E{r}"].number_format = "+0%;-0%;0%"
        for col, fmt in (("F", "0.00"), ("G", "#,##0;[Red]-#,##0"), ("H", "0.00;[Red]-0.00")):
            ws[f"{col}{r}"] = 0
            ws[f"{col}{r}"].number_format = fmt
    if data_tables:
        ws[f"F{first}"] = DataTableFormula(ref=f"F{first}:H{end}", r1="B10")
    ws[f"E{end + 1}"] = "Built with What-If Analysis > Data Table, column input cell = B10 (price shock)."
    ws[f"E{end + 1}"].font = F_NOTE

    # Two-variable Data Table: shock down, actual volume across, margin in the body.
    vols = [round(forecast * k) for k in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3)]
    top = end + 3
    ws[f"E{top}"] = "Data Table 2: margin (EUR) by price shock (rows) and actual volume in MWh (columns)"
    ws[f"E{top}"].font = F_H2
    corner = top + 1
    ws[f"E{corner}"] = "=Sc_Margin"
    ws[f"E{corner}"].number_format = '"Margin";"Margin";"Margin"'
    for j, v in enumerate(vols):
        c = ws.cell(row=corner, column=6 + j, value=v)
        c.font, c.fill, c.number_format = F_HEADER, FILL_HEADER, "#,##0"
    for i, s in enumerate(shocks):
        r = corner + 1 + i
        c = ws[f"E{r}"]
        c.value, c.font, c.fill, c.number_format = s, F_HEADER, FILL_HEADER, "+0%;-0%;0%"
        for j in range(len(vols)):
            cell = ws.cell(row=r, column=6 + j, value=0)
            cell.number_format = "#,##0;[Red]-#,##0"
    last_col = get_column_letter(6 + len(vols) - 1)
    body = f"F{corner + 1}:{last_col}{corner + len(shocks)}"
    if data_tables:
        ws[f"F{corner + 1}"] = DataTableFormula(ref=body, dt2D=True, r1="B6", r2="B10")
    ws.conditional_formatting.add(
        body,
        ColorScaleRule(
            start_type="min",
            start_color="F8696B",
            mid_type="num",
            mid_value=0,
            mid_color="FFFFFF",
            end_type="max",
            end_color="63BE7B",
        ),
    )
    note = corner + len(shocks) + 1
    ws[f"E{note}"] = (
        "Row input cell = B6 (actual volume), column input cell = B10 (price shock). The hedge is fixed in MWh, "
        "so extra volume in a price spike is bought at the shocked spot price: volume and price risk compound."
    )
    ws[f"E{note}"].font = F_NOTE

    # A single-point check so a reader can confirm the Data Table without trusting it.
    chk = note + 2
    ws[f"E{chk}"] = "Check: +100% shock, 130% volume, computed directly"
    ws[f"E{chk}"].font = Font(bold=True)
    ws[f"J{chk}"] = (
        f"={last_col}{corner}*Sc_Tariff-Sc_Forecast*Sc_Hedge*Sc_Forward"
        f"-({last_col}{corner}-Sc_Forecast*Sc_Hedge)*Sc_SpotBase*(1+E{corner + shocks.index(1.0) + 1})"
    )
    ws[f"K{chk}"] = f'=IF(ABS(J{chk}-{last_col}{corner + shocks.index(1.0) + 1})<0.01,"OK","Mismatch")'
    ws[f"J{chk}"].number_format = "#,##0;[Red]-#,##0"
    _widths(ws, {"A": 34, "B": 13, "C": 44, "E": 12, "F": 11, "G": 13, "H": 13, "I": 11, "J": 11, "K": 11, "L": 11})


def build_dashboard(wb: Workbook, df: pd.DataFrame, last: int) -> None:
    ws = wb["Dashboard"]
    ws["A1"] = "German Power Price Risk Dashboard"
    ws["A1"].font = F_TITLE
    ws["A2"] = '="DE-LU day-ahead, "&TEXT(MIN(d_Date),"d mmm yyyy")&" to "&TEXT(MAX(d_Date),"d mmm yyyy")'
    ws["A2"].font = F_NOTE
    ws["H2"] = "Last refreshed"
    ws["I2"] = datetime.now().replace(microsecond=0)
    ws["I2"].number_format = "yyyy-mm-dd hh:mm"
    _name(wb, "LastRefresh", _abs("Dashboard", "I2"))

    kpis = [
        ("Average base price", "=AVERAGE(d_Base)", '0.0" €/MWh"'),
        ("Latest base price", "=INDEX(d_Base,ROWS(d_Base))", '0.0" €/MWh"'),
        ("30-day volatility (latest)", "=INDEX(d_RollVol,ROWS(d_RollVol))", '0.0" €/MWh"'),
        ("Next-day hist. VaR", "=Next_HistVaR", '0.0" €/MWh"'),
        ("Next-day VaR on position", "=Next_HistVaR_EUR", '#,##0" €"'),
        ("Hist. VaR breaches", '=BT_HistBreaches&" vs "&TEXT(BT_Expected,"0.0")&" expected"', "@"),
        ("Hist. VaR model (Kupiec)", "=BT_HistResult", "@"),
        ("Negative-price hours", "=SUM(d_NegHours)", "#,##0"),
    ]
    for i, (label, formula, fmt) in enumerate(kpis):
        col = 1 + (i % 4) * 2
        row = 4 if i < 4 else 7
        lab = ws.cell(row=row, column=col, value=label)
        val = ws.cell(row=row + 1, column=col, value=formula)
        lab.font, lab.fill = Font(bold=True, color="595959", size=9), FILL_KPI
        val.font, val.fill, val.number_format = F_KPI, FILL_KPI, fmt
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
        ws.merge_cells(start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + 1)
        val.alignment = Alignment(horizontal="left")

    ws["A10"] = (
        "Pivot charts (monthly price, negative hours, breaches by year) are added by the BuildDashboard / "
        "RefreshDashboard macro below. See the README sheet for one-time setup."
    )
    ws["A10"].font = F_NOTE

    data = wb["Data"]
    price = LineChart()
    price.title = "Daily base price (EUR/MWh)"
    price.add_data(Reference(data, min_col=6, min_row=HEADER_ROW, max_row=last), titles_from_data=True)
    price.set_categories(Reference(data, min_col=1, min_row=FIRST_ROW, max_row=last))
    price.x_axis.number_format = "mmm yy"
    price.legend = None
    price.series[0].graphicalProperties.line.width = 9_525
    price.height, price.width = 8, 16
    _show_axes(price)
    ws.add_chart(price, "A12")

    var_chart = LineChart()
    var_chart.title = "Rolling 30-day volatility and 1-day VaR (EUR/MWh)"
    for header in ("RollVol", "HistVaR"):
        col = data[f"{COL[header]}1"].column
        var_chart.add_data(Reference(data, min_col=col, min_row=HEADER_ROW, max_row=last), titles_from_data=True)
    var_chart.set_categories(Reference(data, min_col=1, min_row=FIRST_ROW, max_row=last))
    var_chart.x_axis.number_format = "mmm yy"
    for s in var_chart.series:
        s.graphicalProperties.line.width = 12_700
    var_chart.height, var_chart.width = 8, 16
    _show_axes(var_chart)
    ws.add_chart(var_chart, "J12")
    _widths(ws, {get_column_letter(j): 14 for j in range(1, 19)})
    ws.column_dimensions["I"].width = 17


README_ROWS: list[tuple[str, str]] = [
    (
        "Purpose",
        "Measure the 1-day price risk of buying German power at the day-ahead auction, test whether the VaR "
        "models hold up out of sample, and show how a supplier's margin reacts to price and volume shocks.",
    ),
    (
        "Data",
        "Bundesnetzagentur SMARD, bidding zone DE-LU, 2023-01-01 to 2025-12-31, loaded into a PostgreSQL star "
        "schema by this repo's ETL. risk_workbook/export.py aggregates hourly prices to local calendar days.",
    ),
    (
        "Daily price",
        "Base price = mean of all hourly prices of the local day (23 or 25 hours on DST days). Peak = "
        "Mon-Fri 08:00-20:00; blank on weekends.",
    ),
    (
        "Risk factor",
        "Absolute daily change in the base price (EUR/MWh). Log or percentage returns are undefined "
        "because prices reach zero and go negative. Absolute changes also map straight to EUR P&L.",
    ),
    (
        "Position",
        "A buyer that must purchase Pos_MWh at the day-ahead price every day (short power). A price rise is "
        "a loss: P&L per MWh = -change. Mark-to-market against the previous day's price; no hedges.",
    ),
    (
        "Volatility",
        "Sample standard deviation (STDEV.S) of the last Vol_Window daily changes, in EUR/MWh. "
        "Annualised with SQRT(365) because power is delivered every calendar day; this assumes "
        "independent changes, which day-ahead prices (mean-reverting, weekly cycle) do not satisfy.",
    ),
    ("Historical VaR", "-PERCENTILE.INC(P&L, 1 - confidence): the empirical quantile, no distribution assumed."),
    (
        "Parametric VaR",
        "-(mean + NORM.S.INV(1 - confidence) x std dev): assumes normally distributed changes. Mean "
        "included. Fat tails (see excess kurtosis on Returns) make it understate extreme losses.",
    ),
    (
        "Backtest",
        "Each day's VaR is estimated from the previous VaR_Window days only, then compared with that day's "
        "P&L. A breach is a loss larger than VaR. Kupiec's proportion-of-failures likelihood-ratio test "
        "(chi-squared, 1 df) checks whether the breach rate matches 1 - confidence.",
    ),
    (
        "Limits of the backtest",
        "Overlapping windows make consecutive VaR estimates highly dependent; Kupiec tests "
        "only the count, not clustering of breaches (Christoffersen's test would). Weekend "
        "and holiday days are included, so Monday changes mix two regimes.",
    ),
    (
        "Scenario",
        "Hypothetical supplier with a fixed tariff and a forward hedge fixed in MWh. Margin = actual volume x "
        "tariff - hedged MWh x forward - (actual - hedged) x shocked spot. The shock scales the last 30-day "
        "average spot price. Ignores grid fees, taxes, balancing costs, shaping and the hourly profile.",
    ),
    (
        "Data Tables",
        "Scenario sheet uses Excel What-If Data Tables ({=TABLE()}). If Excel is set to 'Automatic except "
        "for data tables', press F9. The check cell below Data Table 2 recomputes one entry directly.",
    ),
    ("Colour code", "Yellow cells with blue text are inputs. Everything else is a formula."),
    (
        "Named inputs",
        "Vol_Window (Returns!B4), VaR_Conf (VaR!B4), VaR_Window (VaR!B5), Pos_MWh (VaR!B6), Sc_* "
        "(Scenario!B5:B10). d_* names cover the data columns and are resized by the refresh macro.",
    ),
    (
        "Refresh",
        "1) make risk-export (or python -m risk_workbook.export) writes prices_daily.csv next to the "
        "workbook. 2) In Excel click Refresh Dashboard: it imports the CSV into tblDaily, resizes names and "
        "charts, rebuilds the pivot tables and recalculates.",
    ),
    (
        "One-time macro setup",
        "Open the .xlsx in Excel, Alt+F11 > File > Import > risk_workbook/vba/RiskDashboard.bas, "
        "run AddRefreshButton once, then save as Power_Price_Risk_Workbook.xlsm.",
    ),
    ("Not investment advice", "A teaching model built on public data."),
]


def build_readme(wb: Workbook) -> None:
    ws = wb.create_sheet("README", 1)
    ws["A1"] = "Assumptions and method"
    ws["A1"].font = F_TITLE
    for i, (key, text) in enumerate(README_ROWS):
        r = 3 + i
        ws[f"A{r}"] = key
        ws[f"A{r}"].font = Font(bold=True)
        ws[f"B{r}"] = text
        ws[f"B{r}"].alignment = Alignment(wrap_text=True, vertical="top")
        ws[f"A{r}"].alignment = Alignment(vertical="top")
    _widths(ws, {"A": 24, "B": 120})


def build_workbook(df: pd.DataFrame, path: Path = WORKBOOK_PATH, data_tables: bool = True) -> Path:
    """Write the workbook. data_tables=False leaves the What-If grids empty: verify.py uses that, because
    LibreOffice's emulation of Excel Data Tables writes into the model's input cells while it recalculates."""
    if len(df) < VAR_WINDOW + 30:
        raise ValueError(f"Need at least {VAR_WINDOW + 30} days for the backtest, got {len(df)}")
    wb = Workbook()
    wb.active.title = "Dashboard"
    last = build_data(wb, df)
    build_returns(wb, last)
    build_var(wb, last)
    build_scenario(wb, df, data_tables)
    build_dashboard(wb, df, last)
    build_readme(wb)
    wb.move_sheet("Data", offset=len(wb.sheetnames))  # data last, presentation sheets first
    wb.calculation.fullCalcOnLoad = True
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, help="Build from this export instead of querying the warehouse")
    parser.add_argument("--source", choices=["warehouse", "parquet"], default="warehouse")
    parser.add_argument("--out", type=Path, default=WORKBOOK_PATH)
    args = parser.parse_args(argv)
    setup_logging()

    if args.csv:
        df = pd.read_csv(args.csv, parse_dates=["date"])
    else:
        df = export.main(["--source", args.source])
    path = build_workbook(df, args.out)
    log.info("Wrote %s (%d days)", path, len(df))
    return path


if __name__ == "__main__":
    main()
