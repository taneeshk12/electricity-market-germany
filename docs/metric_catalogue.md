# Metric catalogue

Generated 2026-11-12 13:08 UTC by `python -m analytics_agent.cli --verify-metrics`. Each example query was validated by the SQL validator and executed as the read-only role `emg_agent_ro`; results below are real.
Source of truth: [`analytics_agent/metrics.py`](../analytics_agent/metrics.py).

## average_day_ahead_price

Time-weighted average of the hourly day-ahead price (each hour counts once).

| | |
|---|---|
| Formula | `AVG(price_eur_mwh)` |
| Tables | `marts.fct_market_hourly` |
| Columns | `price_eur_mwh` |
| Aggregation | mean over hours |
| Unit | EUR/MWh |
| Limitations | Not volume-weighted (traded volumes are not in the data). Monthly/daily marts hold the same mean per period; averaging monthly averages is not equal to the yearly average. |

Example: *What was the average electricity price in 2024?*

```sql
SELECT year, round(avg(price_eur_mwh), 2) AS avg_price_eur_mwh FROM marts.fct_market_hourly GROUP BY year ORDER BY year
```

| year | avg_price_eur_mwh |
|---|---|
| 2023 | 95.18 |
| 2024 | 78.51 |
| 2025 | 89.32 |

## renewable_share

Share of net generation that comes from renewable sources (wind, solar, biomass, hydro, other renewables).

| | |
|---|---|
| Formula | `SUM(renewable_mwh) / SUM(total_gen_mwh)` |
| Tables | `marts.fct_market_hourly`, `marts.mart_market_monthly`, `marts.mart_market_daily` |
| Columns | `renewable_mwh`, `total_gen_mwh` |
| Aggregation | energy-weighted ratio of sums |
| Unit | fraction 0–1 (×100 for %) |
| Limitations | Share of net generation (SMARD convention), not of gross consumption as in official German targets. Never average hourly or monthly shares. Pumped storage counts in the total but is not renewable. |

Example: *What was the renewable share per year?*

```sql
SELECT year, round(100 * sum(renewable_mwh) / sum(total_gen_mwh), 1) AS renewable_share_pct FROM marts.fct_market_hourly GROUP BY year ORDER BY year
```

| year | renewable_share_pct |
|---|---|
| 2023 | 55.50 |
| 2024 | 58.60 |
| 2025 | 58.90 |

## total_generation

Total net electricity generation of all sources.

| | |
|---|---|
| Formula | `SUM(total_gen_mwh)  (or SUM(generation_mwh) in fct_generation_hourly)` |
| Tables | `marts.fct_market_hourly`, `marts.fct_generation_hourly`, `marts.mart_market_monthly` |
| Columns | `total_gen_mwh`, `generation_mwh` |
| Aggregation | sum |
| Unit | MWh (÷ 1e6 for TWh) |
| Limitations | Net generation only; 20 source-hours are missing in 2023–2025 (slight understatement). |

Example: *Which month had the highest electricity generation?*

```sql
SELECT year_month, round(total_gen_mwh / 1e6, 2) AS total_gen_twh FROM marts.mart_market_monthly ORDER BY total_gen_mwh DESC LIMIT 1
```

| year_month | total_gen_twh |
|---|---|
| 2024-01 | 45.12 |

## generation_by_source

Net generation per source or category (renewable, fossil, nuclear, other).

| | |
|---|---|
| Formula | `SUM(generation_mwh) GROUP BY source_name | category` |
| Tables | `marts.fct_generation_hourly` |
| Columns | `generation_mwh`, `source_name`, `category` |
| Aggregation | sum |
| Unit | MWh |
| Limitations | Nuclear has no data after the shutdown on 2023-04-15. 'other' = pumped storage. |

Example: *How much solar and wind was generated in 2023 and 2024?*

```sql
SELECT year, source_name, round(sum(generation_mwh) / 1e6, 2) AS twh FROM marts.fct_generation_hourly WHERE source_name IN ('solar', 'wind_onshore', 'wind_offshore') AND year IN (2023, 2024) GROUP BY year, source_name ORDER BY year, source_name
```

| year | source_name | twh |
|---|---|---|
| 2023 | solar | 55.80 |
| 2023 | wind_offshore | 23.52 |
| 2023 | wind_onshore | 119.50 |
| 2024 | solar | 63.44 |
| 2024 | wind_offshore | 25.67 |
| 2024 | wind_onshore | 113.03 |

## total_consumption

Total grid load (Netzlast).

| | |
|---|---|
| Formula | `SUM(consumption_mwh)` |
| Tables | `marts.fct_market_hourly`, `marts.mart_market_monthly` |
| Columns | `consumption_mwh` |
| Aggregation | sum |
| Unit | MWh (÷ 1e6 for TWh) |
| Limitations | Grid load, not total electricity consumption including self-generation. |

Example: *What was the total grid load per year?*

```sql
SELECT year, round(sum(consumption_mwh) / 1e6, 1) AS grid_load_twh FROM marts.fct_market_hourly GROUP BY year ORDER BY year
```

| year | grid_load_twh |
|---|---|
| 2023 | 463.10 |
| 2024 | 470.40 |
| 2025 | 470.70 |

## residual_load

Demand not covered by wind and solar: grid load minus wind and solar generation.

| | |
|---|---|
| Formula | `consumption_mwh - variable_renewable_mwh; averaged: AVG(residual_load_mwh)` |
| Tables | `marts.fct_market_hourly` |
| Columns | `residual_load_mwh` |
| Aggregation | mean over hours |
| Unit | MWh per hour (= average MW) |
| Limitations | Uses grid load, so imports/exports and storage are not netted out. |

Example: *What was the average residual load in negative-price hours vs other hours?*

```sql
SELECT is_negative_price, round(avg(residual_load_mwh) / 1000, 1) AS avg_residual_load_gw FROM marts.fct_market_hourly GROUP BY is_negative_price
```

| is_negative_price | avg_residual_load_gw |
|---|---|
| False | 31.60 |
| True | 4.00 |

## peak_demand

Highest hourly grid load in a period.

| | |
|---|---|
| Formula | `MAX(consumption_mwh)` |
| Tables | `marts.fct_market_hourly`, `marts.mart_market_monthly` |
| Columns | `consumption_mwh`, `peak_hourly_load_mwh` |
| Aggregation | max |
| Unit | MWh in one hour (= average MW; ÷ 1000 for GW) |
| Limitations | Hourly average, so short intra-hour peaks are smoothed. |

Example: *What was the peak demand in each year?*

```sql
SELECT year, round(max(consumption_mwh) / 1000, 1) AS peak_load_gw FROM marts.fct_market_hourly GROUP BY year ORDER BY year
```

| year | peak_load_gw |
|---|---|
| 2023 | 74.50 |
| 2024 | 76.30 |
| 2025 | 76.40 |

## negative_price_hours

Number (and share) of hours with a negative day-ahead price.

| | |
|---|---|
| Formula | `COUNT(*) FILTER (WHERE is_negative_price); share = that / COUNT(*)` |
| Tables | `marts.fct_market_hourly`, `marts.mart_market_monthly`, `marts.mart_market_daily` |
| Columns | `is_negative_price`, `negative_price_hours` |
| Aggregation | count |
| Unit | hours / fraction |
| Limitations | Since 2025-10-01 an hour is the mean of four quarter-hour prices, so a single negative quarter-hour does not make the hour negative (counts slightly conservative). |

Example: *What percentage of hours had negative prices in each year?*

```sql
SELECT year, count(*) FILTER (WHERE is_negative_price) AS negative_hours, round(100.0 * count(*) FILTER (WHERE is_negative_price) / count(*), 2) AS negative_pct FROM marts.fct_market_hourly GROUP BY year ORDER BY year
```

| year | negative_hours | negative_pct |
|---|---|---|
| 2023 | 301 | 3.44 |
| 2024 | 457 | 5.20 |
| 2025 | 576 | 6.58 |

## price_volatility

Sample standard deviation of hourly day-ahead prices within a period.

| | |
|---|---|
| Formula | `STDDEV_SAMP(price_eur_mwh)` |
| Tables | `marts.mart_market_monthly`, `marts.fct_market_hourly` |
| Columns | `price_stddev_eur_mwh`, `price_eur_mwh` |
| Aggregation | standard deviation |
| Unit | EUR/MWh |
| Limitations | Measures dispersion of hourly prices, not return volatility. |

Example: *Which month had the most volatile prices?*

```sql
SELECT year_month, round(price_stddev_eur_mwh, 2) AS price_stddev FROM marts.mart_market_monthly ORDER BY price_stddev_eur_mwh DESC LIMIT 3
```

| year_month | price_stddev |
|---|---|
| 2024-12 | 92.08 |
| 2024-11 | 64.95 |
| 2025-01 | 59.92 |

## peak_offpeak_spread

Average peak price (Mon–Fri 08–20 local) minus average off-peak price.

| | |
|---|---|
| Formula | `AVG(price) FILTER (WHERE is_peak) - AVG(price) FILTER (WHERE NOT is_peak)` |
| Tables | `marts.fct_market_hourly` |
| Columns | `price_eur_mwh`, `is_peak` |
| Aggregation | difference of means |
| Unit | EUR/MWh |
| Limitations | Public holidays on weekdays count as peak (EEX definition). |

Example: *How did the peak/off-peak price spread develop?*

```sql
SELECT year, round(avg(price_eur_mwh) FILTER (WHERE is_peak) - avg(price_eur_mwh) FILTER (WHERE NOT is_peak), 2) AS spread_eur_mwh FROM marts.fct_market_hourly GROUP BY year ORDER BY year
```

| year | spread_eur_mwh |
|---|---|
| 2023 | 17.18 |
| 2024 | 14.55 |
| 2025 | 4.71 |

## residual_load_price_correlation

Pearson correlation between hourly residual load and price.

| | |
|---|---|
| Formula | `CORR(residual_load_mwh, price_eur_mwh)` |
| Tables | `marts.fct_market_hourly` |
| Columns | `residual_load_mwh`, `price_eur_mwh` |
| Aggregation | correlation |
| Unit | r (−1 to 1) |
| Limitations | Association, not causation; fuel and CO2 prices are not in the data. |

Example: *What was the relationship between residual load and electricity prices?*

```sql
SELECT round(corr(residual_load_mwh, price_eur_mwh)::numeric, 3) AS r, round(regr_r2(price_eur_mwh, residual_load_mwh)::numeric, 3) AS r_squared FROM marts.fct_market_hourly
```

| r | r_squared |
|---|---|
| 0.83 | 0.70 |
