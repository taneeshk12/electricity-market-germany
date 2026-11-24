# Power Price Risk Workbook

An Excel risk workbook built on this repo's German power price warehouse. A Python script exports daily
DE-LU day-ahead prices from PostgreSQL and builds the workbook. Every risk number in it is a live Excel
formula, and a pandas reference implementation checks all of them.

**Download:** [`output/Power_Price_Risk_Workbook.xlsx`](output/Power_Price_Risk_Workbook.xlsx)

## What's inside

| Sheet | Contents |
|---|---|
| **Dashboard** | KPIs (average and latest price, 30-day volatility, next-day VaR in €/MWh and € on the position, backtest result, negative-price hours), price and volatility/VaR charts, and pivot charts once the macro has run |
| **README** | Assumptions and method, in the workbook itself |
| **Returns** | Daily price-change statistics (volatility, skew, excess kurtosis), a histogram with a normal-fit overlay, and the price with 30-day rolling volatility |
| **VaR** | Historical vs. parametric VaR at 95/99 %, next-day VaR, a rolling out-of-sample backtest with Kupiec's POF test, and breaches by year |
| **Scenario** | A hypothetical supplier (fixed tariff, forward hedge fixed in MWh), a one-variable Data Table (price shock) and a two-variable Data Table (price shock × actual volume) with a colour scale |
| **Data** | `tblDaily`: 1,096 days of warehouse data plus per-day formula columns (change, buyer P&L, rolling vol, rolling VaR, breach flags) |

## Results (2023–2025, 1,000 MWh/day buyer)

| | Historical | Parametric (normal) |
|---|---|---|
| 1-day VaR 95 %, full sample | 52.20 €/MWh | 49.42 €/MWh |
| 1-day VaR 99 %, full sample | **92.01 €/MWh** | **69.86 €/MWh** |
| Backtest at 99 %, 250-day window: breaches / expected | 11 / 8.5 | 23 / 8.5 |
| Kupiec p-value | 0.40: not rejected | 0.00003: **rejected** |

Daily price changes have an excess kurtosis of **3.8**. The normal model understates the 99 % loss by about
24 % and breaches almost three times as often as it should. Historical simulation holds up.
In the scenario, at the default inputs a +50 % price spike with 10 % more volume than forecast cuts the
monthly margin from €596k to €94k, because the extra volume is bought at the spiked spot price.

## Key assumptions

- **Risk factor = absolute daily change in €/MWh**, not % or log returns: German prices hit zero and go
  negative, where those are undefined.
- **Position**: a buyer purchasing a fixed volume at day-ahead every day; a price rise is a loss.
- **Historical VaR** = `-PERCENTILE.INC(P&L, 1-α)`; **parametric** = `-(μ + NORM.S.INV(1-α)·σ)`.
- **Backtest**: each day's VaR uses only the previous 250 days. Kupiec tests the breach count, not clustering.
- **Scenario** ignores grid fees, taxes, balancing and hourly shape costs.

The full list is on the workbook's README sheet.

## Build and verify

```bash
make db-up
make risk-workbook   # export from PostgreSQL -> output/prices_daily.csv, build output/*.xlsx
make risk-verify     # recalculate in headless LibreOffice, compare ~7,700 values with metrics.py
```

No database? `python -m risk_workbook.build_workbook --source parquet` uses `data/processed/` instead.

`risk-verify` checks every formula except the Data Table grids. LibreOffice's emulation of Excel Data Tables
writes into the model's input cells, so the check runs on a copy built without them. It then prints the
expected grid so you can compare it with Excel. The Scenario sheet also has a check cell that recomputes one
grid entry directly.

## One-click refresh (VBA)

[`vba/RiskDashboard.bas`](vba/RiskDashboard.bas) does the following in one click:

1. imports `prices_daily.csv` from the workbook's folder into `tblDaily`,
2. refills the formula columns and resizes the named ranges and charts,
3. rebuilds three pivot tables (monthly price, negative hours, VaR breaches) and their pivot charts on the Dashboard,
4. recalculates everything and stamps the refresh time.

One-time setup in Excel: open the `.xlsx`, press Alt+F11 (Mac: Tools > Macros > Visual Basic Editor), then
File > Import File… > `RiskDashboard.bas`. Run `AddRefreshButton` once and save as `.xlsm`.
After that, the refresh cycle is `make risk-export`, then click **Refresh Dashboard**.

## Files

| File | Role |
|---|---|
| `export.py` | SQL against `v_hourly` + `dim_date` → daily CSV (or from parquet) |
| `build_workbook.py` | openpyxl: sheets, formulas, named ranges, charts, Data Tables |
| `metrics.py` | pandas/stdlib reference for every formula (unit-tested) |
| `verify.py` | LibreOffice recalculation + comparison |
| `vba/RiskDashboard.bas` | refresh, pivots, button |

Data: Bundesnetzagentur | SMARD.de, CC BY 4.0. Not investment advice.
