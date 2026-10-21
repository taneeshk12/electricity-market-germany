# Analysis results

Generated 2026-10-21 12:09 UTC from the PostgreSQL star schema by `src/run_analysis.py`.

## 01_monthly_renewable_share

Q1: How has the renewable share developed over time? Monthly renewable share of net generation, energy-weighted (sum of MWh, not average of hourly shares), with wind and solar split out. Months are local (Europe/Berlin) calendar months.

Query: [`sql/analysis/01_monthly_renewable_share.sql`](../sql/analysis/01_monthly_renewable_share.sql)

| year_month | generation_twh | renewable_share_pct | wind_share_pct | solar_share_pct | fossil_share_pct |
|---|---|---|---|---|---|
| 2023-01 | 44.66 | 51.00 | 39.00 | 1.90 | 42.90 |
| 2023-02 | 41.68 | 44.20 | 29.00 | 5.60 | 49.60 |
| 2023-03 | 43.65 | 52.30 | 33.40 | 8.60 | 40.60 |
| 2023-04 | 36.44 | 55.00 | 27.80 | 15.20 | 39.80 |
| 2023-05 | 33.90 | 62.80 | 24.60 | 23.80 | 34.50 |
| 2023-06 | 32.77 | 59.60 | 18.50 | 27.30 | 38.10 |
| 2023-07 | 34.40 | 65.20 | 29.60 | 22.50 | 32.80 |
| 2023-08 | 32.07 | 56.70 | 21.70 | 20.50 | 40.70 |
| 2023-09 | 32.42 | 54.30 | 20.60 | 20.30 | 43.20 |
| 2023-10 | 38.11 | 57.80 | 37.90 | 8.70 | 39.90 |
| 2023-11 | 41.21 | 55.20 | 40.80 | 3.30 | 42.70 |
| 2023-12 | 43.39 | 57.00 | 44.50 | 1.80 | 41.00 |
| 2024-01 | 45.12 | 55.20 | 41.30 | 3.20 | 43.00 |
| 2024-02 | 39.72 | 59.60 | 42.60 | 5.70 | 38.40 |
| 2024-03 | 38.22 | 57.00 | 31.70 | 12.80 | 40.80 |
| 2024-04 | 35.56 | 64.90 | 33.50 | 18.70 | 32.50 |
| 2024-05 | 33.18 | 64.10 | 23.50 | 26.00 | 33.20 |
| 2024-06 | 32.71 | 63.40 | 22.20 | 27.10 | 33.70 |
| 2024-07 | 33.60 | 63.40 | 21.40 | 27.80 | 33.40 |
| 2024-08 | 32.88 | 60.90 | 20.20 | 27.30 | 36.10 |
| 2024-09 | 33.93 | 62.50 | 31.90 | 18.20 | 35.00 |
| 2024-10 | 34.87 | 54.40 | 30.60 | 10.30 | 43.20 |
| 2024-11 | 38.79 | 47.50 | 32.30 | 4.00 | 50.70 |
| 2024-12 | 40.34 | 54.20 | 40.20 | 2.60 | 43.90 |
| 2025-01 | 42.54 | 51.90 | 37.10 | 3.80 | 46.10 |
| 2025-02 | 37.68 | 44.40 | 25.30 | 8.00 | 53.60 |
| 2025-03 | 37.84 | 51.80 | 22.20 | 18.40 | 45.90 |
| 2025-04 | 33.61 | 59.60 | 20.70 | 26.80 | 37.50 |
| 2025-05 | 34.63 | 70.00 | 28.20 | 29.70 | 27.20 |
| 2025-06 | 34.63 | 73.40 | 30.50 | 30.60 | 24.00 |
| 2025-07 | 33.71 | 63.00 | 23.00 | 27.00 | 34.60 |
| 2025-08 | 32.09 | 66.50 | 22.40 | 30.30 | 30.90 |
| 2025-09 | 34.62 | 65.70 | 35.20 | 18.70 | 32.20 |
| 2025-10 | 39.81 | 61.70 | 41.80 | 9.20 | 36.40 |
| 2025-11 | 38.57 | 49.80 | 33.00 | 5.80 | 48.30 |
| 2025-12 | 39.54 | 55.20 | 40.40 | 3.80 | 43.00 |

## 02_yoy_comparison

Year-over-year comparison of the key KPIs, using LAG() to compute the change vs. the previous year.

Query: [`sql/analysis/02_yoy_comparison.sql`](../sql/analysis/02_yoy_comparison.sql)

| year | avg_price_eur_mwh | avg_price_yoy_pct | renewable_share_pct | renewable_share_yoy_pp | generation_twh | load_twh | load_yoy_pct | negative_hours | negative_hours_yoy_pct |
|---|---|---|---|---|---|---|---|---|---|
| 2023 | 95.18 |  | 55.50 |  | 454.70 | 463.10 |  | 301 |  |
| 2024 | 78.51 | -17.50 | 58.60 | 3.10 | 438.90 | 470.40 | 1.60 | 457 | 51.80 |
| 2025 | 89.32 | 13.80 | 58.90 | 0.30 | 439.30 | 470.70 | 0.10 | 576 | 26.00 |

## 03_price_by_renewable_share_bucket

Q2: How strongly does renewable generation affect the price? Hours bucketed by their renewable share (20 %-buckets); average/median price and share of negative hours.

Query: [`sql/analysis/03_price_by_renewable_share_bucket.sql`](../sql/analysis/03_price_by_renewable_share_bucket.sql)

| renewable_share_bucket | hours | avg_price_eur_mwh | median_price_eur_mwh | negative_hours_pct |
|---|---|---|---|---|
| 0–20 % | 380 | 190.51 | 162.38 | 0.00 |
| 20–40 % | 5,684 | 131.48 | 123.60 | 0.00 |
| 40–60 % | 8,402 | 103.16 | 100.71 | 0.00 |
| 60–80 % | 8,837 | 66.83 | 72.40 | 1.60 |
| 80–100 % | 3,001 | 9.58 | 0.81 | 39.70 |

## 04_price_driver_correlation

Q2 (quantified): correlation and simple linear slope between price and its drivers, per year. corr() = Pearson correlation; regr_slope() = EUR/MWh change per additional GW (1 GW for 1 h = 1,000 MWh). Residual load (load minus wind and solar) captures demand AND renewables in one variable.

Query: [`sql/analysis/04_price_driver_correlation.sql`](../sql/analysis/04_price_driver_correlation.sql)

| year | corr_price_renewable_share | corr_price_wind_solar | corr_price_load | corr_price_residual_load | eur_per_gw_wind_solar | eur_per_gw_residual_load | r2_residual_load |
|---|---|---|---|---|---|---|---|
| 2023 | -0.79 | -0.63 | 0.38 | 0.87 | -2.30 | 3.03 | 0.75 |
| 2024 | -0.72 | -0.61 | 0.27 | 0.79 | -2.36 | 3.06 | 0.62 |
| 2025 | -0.79 | -0.71 | 0.35 | 0.88 | -2.58 | 3.02 | 0.77 |
| All years | -0.77 | -0.64 | 0.32 | 0.83 | -2.42 | 3.03 | 0.70 |

## 05_rolling_7day_avg_price

Rolling 7-day average of the daily average day-ahead price (window function). The first 6 days have an incomplete window and are flagged.

Query: [`sql/analysis/05_rolling_7day_avg_price.sql`](../sql/analysis/05_rolling_7day_avg_price.sql)

| date | daily_avg_price | rolling_7d_avg_price | incomplete_window |
|---|---|---|---|
| 2023-01-01 | 14.91 | 14.91 | True |
| 2023-01-02 | 123.82 | 69.37 | True |
| 2023-01-03 | 145.95 | 94.90 | True |
| 2023-01-04 | 58.94 | 85.91 | True |
| 2023-01-05 | 107.46 | 90.22 | True |
| 2023-01-06 | 117.47 | 94.76 | True |
| 2023-01-07 | 88.81 | 93.91 | False |
| 2023-01-08 | 68.94 | 101.63 | False |
| 2023-01-09 | 129.29 | 102.41 | False |
| 2023-01-10 | 123.13 | 99.15 | False |
| 2023-01-11 | 84.08 | 102.74 | False |
| 2023-01-12 | 70.74 | 97.50 | False |
| 2023-01-13 | 66.64 | 90.23 | False |
| 2023-01-14 | 29.34 | 81.74 | False |
| 2023-01-15 | 9.26 | 73.21 | False |
| 2023-01-16 | 128.75 | 73.14 | False |
| 2023-01-17 | 133.57 | 74.63 | False |
| 2023-01-18 | 143.76 | 83.15 | False |
| 2023-01-19 | 148.21 | 94.22 | False |
| 2023-01-20 | 180.66 | 110.51 | False |
| 2023-01-21 | 144.39 | 126.94 | False |
| 2023-01-22 | 151.15 | 147.21 | False |
| 2023-01-23 | 202.73 | 157.78 | False |
| 2023-01-24 | 202.69 | 167.66 | False |
| 2023-01-25 | 181.74 | 173.08 | False |
| 2023-01-26 | 167.67 | 175.86 | False |
| 2023-01-27 | 168.76 | 174.16 | False |
| 2023-01-28 | 144.70 | 174.21 | False |
| 2023-01-29 | 123.59 | 170.27 | False |
| 2023-01-30 | 74.21 | 151.91 | False |
| 2023-01-31 | 117.32 | 139.71 | False |
| 2023-02-01 | 93.08 | 127.05 | False |
| 2023-02-02 | 136.15 | 122.54 | False |
| 2023-02-03 | 102.61 | 113.09 | False |
| 2023-02-04 | 146.01 | 113.28 | False |
| 2023-02-05 | 131.37 | 114.39 | False |
| 2023-02-06 | 172.96 | 128.50 | False |
| 2023-02-07 | 172.92 | 136.44 | False |
| 2023-02-08 | 152.10 | 144.88 | False |
| 2023-02-09 | 132.54 | 144.36 | False |

*Showing 40 of 1096 rows – full result in `analysis_results/05_rolling_7day_avg_price.csv`.*

## 06_top10_days

Top 10 most expensive and cheapest days (daily average price), with the day's renewable share and holiday/weekend context to explain them.

Query: [`sql/analysis/06_top10_days.sql`](../sql/analysis/06_top10_days.sql)

| list | rank | date | weekday_name | holiday | avg_price_eur_mwh | renewable_share_pct | avg_wind_gw | avg_solar_gw |
|---|---|---|---|---|---|---|---|---|
| most expensive | 1 | 2024-12-12 | Thursday |  | 395.34 | 18.50 | 1.50 | 0.60 |
| most expensive | 2 | 2024-12-11 | Wednesday |  | 266.54 | 20.10 | 2.50 | 0.50 |
| most expensive | 3 | 2025-01-20 | Monday |  | 231.36 | 28.70 | 5.00 | 3.20 |
| most expensive | 4 | 2024-11-06 | Wednesday |  | 231.09 | 18.50 | 0.30 | 1.50 |
| most expensive | 5 | 2025-01-15 | Wednesday |  | 222.18 | 27.90 | 7.60 | 1.00 |
| most expensive | 6 | 2025-11-25 | Tuesday |  | 220.52 | 24.90 | 5.50 | 1.30 |
| most expensive | 7 | 2023-01-23 | Monday |  | 202.73 | 21.70 | 5.30 | 0.60 |
| most expensive | 8 | 2023-01-24 | Tuesday |  | 202.69 | 19.30 | 3.70 | 0.50 |
| most expensive | 9 | 2024-12-04 | Wednesday |  | 182.47 | 29.40 | 7.30 | 1.50 |
| most expensive | 10 | 2023-01-25 | Wednesday |  | 181.74 | 19.90 | 4.50 | 0.30 |
| cheapest | 1 | 2023-07-02 | Sunday |  | -53.87 | 79.10 | 23.00 | 10.70 |
| cheapest | 2 | 2023-12-24 | Sunday |  | -3.37 | 81.80 | 40.20 | 0.50 |
| cheapest | 3 | 2025-10-04 | Saturday |  | -0.29 | 86.50 | 39.40 | 3.60 |
| cheapest | 4 | 2023-12-25 | Monday | Christmas Day | 0.41 | 79.20 | 35.30 | 1.20 |
| cheapest | 5 | 2025-01-01 | Wednesday | New Year's Day | 0.95 | 80.60 | 40.60 | 2.40 |
| cheapest | 6 | 2025-10-05 | Sunday |  | 1.73 | 86.00 | 38.80 | 4.90 |
| cheapest | 7 | 2024-05-12 | Sunday |  | 1.78 | 76.60 | 12.00 | 15.50 |
| cheapest | 8 | 2024-11-24 | Sunday |  | 3.97 | 80.80 | 41.30 | 2.20 |
| cheapest | 9 | 2024-05-01 | Wednesday | Labour Day | 4.39 | 79.10 | 17.70 | 14.40 |
| cheapest | 10 | 2023-12-29 | Friday |  | 6.36 | 81.50 | 44.40 | 1.30 |

## 07_negative_hours_by_month

Q3: When do negative prices occur? Negative-price hours per month, with their average price. Months without negative hours are included (LEFT JOIN on the full month list) so the series has no gaps.

Query: [`sql/analysis/07_negative_hours_by_month.sql`](../sql/analysis/07_negative_hours_by_month.sql)

| year_month | negative_hours | avg_negative_price_eur_mwh | min_price_eur_mwh |
|---|---|---|---|
| 2023-01 | 14 | -2.48 | -5.40 |
| 2023-02 | 0 |  |  |
| 2023-03 | 9 | -1.91 | -6.02 |
| 2023-04 | 11 | -2.99 | -8.82 |
| 2023-05 | 33 | -28.58 | -129.96 |
| 2023-06 | 20 | -11.55 | -36.35 |
| 2023-07 | 56 | -39.03 | -500.00 |
| 2023-08 | 23 | -6.69 | -21.77 |
| 2023-09 | 22 | -1.77 | -5.74 |
| 2023-10 | 38 | -1.52 | -11.07 |
| 2023-11 | 3 | -0.04 | -0.08 |
| 2023-12 | 72 | -2.47 | -13.37 |
| 2024-01 | 16 | -1.05 | -4.84 |
| 2024-02 | 4 | -0.07 | -0.13 |
| 2024-03 | 12 | -3.55 | -9.98 |
| 2024-04 | 50 | -19.83 | -65.06 |
| 2024-05 | 78 | -18.71 | -135.45 |
| 2024-06 | 64 | -12.71 | -80.01 |
| 2024-07 | 81 | -12.01 | -73.96 |
| 2024-08 | 68 | -11.16 | -59.96 |
| 2024-09 | 40 | -3.31 | -24.00 |
| 2024-10 | 25 | -2.15 | -15.69 |
| 2024-11 | 11 | -0.72 | -1.86 |
| 2024-12 | 8 | -0.61 | -2.06 |
| 2025-01 | 14 | -0.11 | -1.01 |
| 2025-02 | 0 |  |  |
| 2025-03 | 30 | -5.48 | -26.07 |
| 2025-04 | 75 | -19.56 | -129.81 |
| 2025-05 | 129 | -16.81 | -250.32 |
| 2025-06 | 141 | -11.69 | -99.01 |
| 2025-07 | 12 | -1.09 | -2.26 |
| 2025-08 | 64 | -5.77 | -61.08 |
| 2025-09 | 60 | -6.38 | -53.40 |
| 2025-10 | 51 | -1.16 | -4.98 |
| 2025-11 | 0 |  |  |
| 2025-12 | 0 |  |  |

## 08_negative_hours_by_hour

Q3: Negative-price hours by local hour of day, split by season.

Query: [`sql/analysis/08_negative_hours_by_hour.sql`](../sql/analysis/08_negative_hours_by_hour.sql)

| hour_label | negative_hours_total | spring | summer | autumn | winter | negative_share_pct |
|---|---|---|---|---|---|---|
| 00:00 | 13 | 0 | 2 | 7 | 4 | 1.20 |
| 01:00 | 24 | 0 | 3 | 9 | 12 | 2.20 |
| 02:00 | 26 | 0 | 3 | 11 | 12 | 2.40 |
| 03:00 | 31 | 0 | 3 | 14 | 14 | 2.80 |
| 04:00 | 32 | 0 | 4 | 13 | 15 | 2.90 |
| 05:00 | 26 | 0 | 5 | 9 | 12 | 2.40 |
| 06:00 | 18 | 0 | 4 | 6 | 8 | 1.60 |
| 07:00 | 19 | 0 | 4 | 6 | 9 | 1.70 |
| 08:00 | 18 | 2 | 7 | 4 | 5 | 1.60 |
| 09:00 | 31 | 5 | 15 | 6 | 5 | 2.80 |
| 10:00 | 70 | 23 | 32 | 10 | 5 | 6.40 |
| 11:00 | 122 | 51 | 48 | 17 | 6 | 11.10 |
| 12:00 | 172 | 71 | 70 | 26 | 5 | 15.70 |
| 13:00 | 207 | 81 | 87 | 36 | 3 | 18.90 |
| 14:00 | 202 | 77 | 87 | 36 | 2 | 18.40 |
| 15:00 | 166 | 65 | 75 | 24 | 2 | 15.10 |
| 16:00 | 106 | 41 | 53 | 10 | 2 | 9.70 |
| 17:00 | 36 | 11 | 22 | 2 | 1 | 3.30 |
| 18:00 | 5 | 0 | 4 | 0 | 1 | 0.50 |
| 19:00 | 1 | 0 | 0 | 0 | 1 | 0.10 |
| 20:00 | 1 | 0 | 0 | 0 | 1 | 0.10 |
| 21:00 | 2 | 0 | 0 | 1 | 1 | 0.20 |
| 22:00 | 2 | 0 | 0 | 1 | 1 | 0.20 |
| 23:00 | 4 | 0 | 1 | 2 | 1 | 0.40 |

## 09_negative_hours_by_day_type

Q3: Why do negative prices occur? Rate of negative hours by day type, and the average market conditions in negative vs. non-negative hours. Holidays take precedence over weekend. Hypothesis: low demand (weekends/holidays) + high solar at midday -> oversupply.

Query: [`sql/analysis/09_negative_hours_by_day_type.sql`](../sql/analysis/09_negative_hours_by_day_type.sql)

| day_type | hours | negative_hours | negative_share_pct | load_gw_when_negative | load_gw_otherwise | solar_gw_when_negative | wind_gw_when_negative | residual_load_gw_when_negative | residual_load_gw_otherwise |
|---|---|---|---|---|---|---|---|---|---|
| Public holiday | 648 | 115 | 17.75 | 43.30 | 44.20 | 16.40 | 24.30 | 2.50 | 23.40 |
| Sunday | 3,744 | 490 | 13.09 | 44.50 | 45.50 | 23.40 | 17.10 | 4.00 | 25.20 |
| Saturday | 3,744 | 273 | 7.29 | 47.60 | 48.20 | 29.20 | 15.30 | 3.20 | 27.00 |
| Weekday | 18,168 | 456 | 2.51 | 55.50 | 56.50 | 28.40 | 22.10 | 5.00 | 34.00 |
| All days | 26,304 | 1,334 | 5.07 | 48.80 | 53.60 | 25.70 | 19.10 | 4.00 | 31.60 |

## 10_daily_profile_summer_winter

Q4: What does a typical day look like in summer vs. winter? Average price, load, solar and wind per local hour of day (meteorological seasons).

Query: [`sql/analysis/10_daily_profile_summer_winter.sql`](../sql/analysis/10_daily_profile_summer_winter.sql)

| season | hour_label | avg_price_eur_mwh | avg_load_gw | avg_solar_gw | avg_wind_gw | avg_residual_load_gw | negative_share_pct |
|---|---|---|---|---|---|---|---|
| Winter | 00:00 | 80.10 | 49.30 | 0.00 | 22.30 | 27.00 | 1.50 |
| Winter | 01:00 | 75.60 | 47.60 | 0.00 | 22.10 | 25.40 | 4.40 |
| Winter | 02:00 | 73.35 | 46.80 | 0.00 | 22.00 | 24.80 | 4.40 |
| Winter | 03:00 | 70.98 | 46.90 | 0.00 | 21.80 | 25.00 | 5.20 |
| Winter | 04:00 | 71.70 | 47.80 | 0.00 | 21.70 | 26.00 | 5.50 |
| Winter | 05:00 | 76.98 | 50.00 | 0.00 | 21.80 | 28.20 | 4.40 |
| Winter | 06:00 | 90.62 | 54.80 | 0.00 | 22.20 | 32.60 | 3.00 |
| Winter | 07:00 | 109.95 | 59.20 | 0.10 | 22.30 | 36.90 | 3.30 |
| Winter | 08:00 | 122.80 | 62.10 | 1.10 | 22.20 | 38.80 | 1.80 |
| Winter | 09:00 | 116.50 | 63.50 | 4.10 | 21.60 | 37.80 | 1.80 |
| Winter | 10:00 | 107.22 | 64.40 | 7.40 | 21.10 | 35.90 | 1.80 |
| Winter | 11:00 | 101.52 | 65.10 | 9.80 | 20.70 | 34.60 | 2.20 |
| Winter | 12:00 | 97.14 | 64.70 | 10.50 | 20.50 | 33.60 | 1.80 |
| Winter | 13:00 | 95.81 | 63.50 | 9.60 | 20.40 | 33.50 | 1.10 |
| Winter | 14:00 | 99.94 | 62.20 | 7.10 | 20.30 | 34.80 | 0.70 |
| Winter | 15:00 | 109.35 | 61.80 | 3.80 | 20.50 | 37.50 | 0.70 |
| Winter | 16:00 | 118.89 | 62.60 | 1.10 | 21.00 | 40.40 | 0.70 |
| Winter | 17:00 | 131.17 | 64.80 | 0.10 | 21.90 | 42.80 | 0.40 |
| Winter | 18:00 | 130.08 | 65.40 | 0.00 | 22.60 | 42.70 | 0.40 |
| Winter | 19:00 | 120.32 | 63.80 | 0.00 | 23.00 | 40.80 | 0.40 |
| Winter | 20:00 | 107.32 | 60.60 | 0.00 | 23.20 | 37.40 | 0.40 |
| Winter | 21:00 | 97.86 | 57.60 | 0.00 | 23.20 | 34.50 | 0.40 |
| Winter | 22:00 | 94.38 | 55.20 | 0.00 | 22.60 | 32.60 | 0.40 |
| Winter | 23:00 | 83.96 | 52.00 | 0.00 | 22.40 | 29.60 | 0.40 |
| Summer | 00:00 | 92.89 | 42.30 | 0.00 | 11.30 | 31.00 | 0.70 |
| Summer | 01:00 | 85.55 | 40.70 | 0.00 | 11.30 | 29.40 | 1.10 |
| Summer | 02:00 | 81.35 | 39.70 | 0.00 | 11.20 | 28.50 | 1.10 |
| Summer | 03:00 | 79.16 | 39.50 | 0.00 | 11.10 | 28.40 | 1.10 |
| Summer | 04:00 | 79.68 | 40.10 | 0.00 | 11.10 | 29.00 | 1.40 |
| Summer | 05:00 | 85.23 | 42.10 | 0.20 | 11.10 | 30.80 | 1.80 |
| Summer | 06:00 | 99.67 | 46.90 | 2.00 | 11.00 | 33.90 | 1.40 |
| Summer | 07:00 | 103.81 | 51.00 | 6.60 | 10.10 | 34.30 | 1.40 |
| Summer | 08:00 | 93.10 | 54.10 | 13.70 | 9.00 | 31.40 | 2.50 |
| Summer | 09:00 | 73.79 | 55.40 | 21.30 | 8.70 | 25.50 | 5.40 |
| Summer | 10:00 | 56.54 | 56.20 | 27.30 | 8.90 | 20.00 | 11.60 |
| Summer | 11:00 | 44.63 | 56.70 | 31.20 | 9.40 | 16.10 | 17.40 |
| Summer | 12:00 | 34.92 | 56.20 | 33.10 | 9.90 | 13.20 | 25.40 |
| Summer | 13:00 | 26.66 | 55.00 | 33.20 | 10.10 | 11.70 | 31.50 |
| Summer | 14:00 | 24.39 | 53.70 | 31.90 | 10.30 | 11.50 | 31.50 |
| Summer | 15:00 | 32.66 | 53.10 | 29.10 | 10.80 | 13.20 | 27.20 |

*Showing 40 of 48 rows – full result in `analysis_results/10_daily_profile_summer_winter.csv`.*

## 11_peak_offpeak_by_year

Peak vs. off-peak price per year. Peak = Mon–Fri 08:00–20:00 local (EEX definition, dim_datetime.is_peak). Also shows the load-weighted price (what an average consumed MWh cost) next to the time-weighted average.

Query: [`sql/analysis/11_peak_offpeak_by_year.sql`](../sql/analysis/11_peak_offpeak_by_year.sql)

| year | peak_price_eur_mwh | offpeak_price_eur_mwh | peak_spread_eur_mwh | avg_price_eur_mwh | load_weighted_price_eur_mwh |
|---|---|---|---|---|---|
| 2023 | 106.24 | 89.06 | 17.18 | 95.18 | 98.31 |
| 2024 | 87.85 | 73.30 | 14.55 | 78.51 | 80.98 |
| 2025 | 92.35 | 87.64 | 4.71 | 89.32 | 92.42 |
| All years | 95.46 | 83.33 | 12.13 | 87.66 | 90.53 |
