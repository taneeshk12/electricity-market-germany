# Data quality report

Generated: 2026-11-12 12:56 UTC · Source: SMARD.de – Bundesnetzagentur | Strommarktdaten (chart-data API) · region DE-LU · retrieved 2026-10-20T21:33:07+00:00 · period 2023-01-01 – 2025-12-31

**Status: ⚠️ PASSED with warnings**

- Warning: biomass: 1 missing hours
- Warning: hydro: 7 missing hours
- Warning: natural_gas: 1 missing hours
- Warning: other_conventional: 9 missing hours
- Warning: solar: 1 missing hours
- Warning: wind_onshore: 1 missing hours

## Check summary

Machine-readable version: [`data_quality_report.json`](data_quality_report.json).

| check | description | expected | actual | severity | status |
|---|---|---|---|---|---|
| price_load_row_count | price/load has exactly one row per hour of the period | 26304 | 26304 | critical | ✅ pass |
| generation_row_count | generation has one row per hour and source (long format) | 315648 | 315648 | critical | ✅ pass |
| null_keys | no NULLs in timestamp or source key columns | 0 | 0 | critical | ✅ pass |
| hourly_continuity | consecutive UTC timestamps are exactly 1 hour apart | 0 gaps | 0 gaps | critical | ✅ pass |
| monotonic_timestamps | UTC timestamps strictly increasing (no duplicates / disorder) | 0 | 0 | critical | ✅ pass |
| expected_frequency | every timestamp lies on a full UTC hour (hourly frequency) | 0 | 0 | critical | ✅ pass |
| dst_days | only DST switch days (last Sunday Mar = 23h, Oct = 25h) deviate from 24h | all irregular days are DST days | 6 irregular days, all DST: True | critical | ✅ pass |
| missing_hours.biomass | hours without a value for biomass | 0 | 1 | warning | ⚠️ warn |
| missing_hours.hard_coal | hours without a value for hard_coal | 0 | 0 | warning | ✅ pass |
| missing_hours.hydro | hours without a value for hydro | 0 | 7 | warning | ⚠️ warn |
| missing_hours.lignite | hours without a value for lignite | 0 | 0 | warning | ✅ pass |
| missing_hours.natural_gas | hours without a value for natural_gas | 0 | 1 | warning | ⚠️ warn |
| missing_hours.other_conventional | hours without a value for other_conventional | 0 | 9 | warning | ⚠️ warn |
| missing_hours.other_renewable | hours without a value for other_renewable | 0 | 0 | warning | ✅ pass |
| missing_hours.pumped_storage | hours without a value for pumped_storage | 0 | 0 | warning | ✅ pass |
| missing_hours.solar | hours without a value for solar | 0 | 1 | warning | ⚠️ warn |
| missing_hours.wind_offshore | hours without a value for wind_offshore | 0 | 0 | warning | ✅ pass |
| missing_hours.wind_onshore | hours without a value for wind_onshore | 0 | 1 | warning | ⚠️ warn |
| missing_hours.price_eur_mwh | hours without a value for price_eur_mwh | 0 | 0 | critical | ✅ pass |
| missing_hours.consumption_mwh | hours without a value for consumption_mwh | 0 | 0 | critical | ✅ pass |
| duplicate_keys | no duplicate (timestamp_utc, source) / timestamp_utc keys after transform | 0 | 0 | critical | ✅ pass |
| conflicting_raw_duplicates | raw chunks contain no timestamps with differing values | 0 | 0 | critical | ✅ pass |
| negative_generation | generation_mwh >= 0 | 0 | 0 | warning | ✅ pass |
| load_range | hourly grid load within [15,000, 120,000] MWh | 0 | 0 | warning | ✅ pass |
| price_limits | day-ahead price within harmonised limits [-500, 4000] | 0 | 0 | critical | ✅ pass |
| smard_reconciliation | our hourly aggregation equals SMARD's hourly series within tolerance | 0 | 0 mismatching hours | critical | ✅ pass |
| raw_resolution | raw series are delivered in 15-minute steps | [15.0] | [15.0] | warning | ✅ pass |

## 0. Source format and time handling

Data comes from SMARD's chart-data JSON API, not the CSV download portal. Values are plain JSON numbers (no German '1.234,5' format or ';' separators) and missing values are `null` (counted below; '-' or other strings would be coerced to NaN and counted as non-numeric). Timestamps are epoch milliseconds (UTC), so DST is unambiguous: the pipeline keys on UTC and derives Europe/Berlin local time plus UTC offset for reporting.

## 1. Row counts

| year | expected_hours | price_load_rows | generation_rows | expected_generation_rows |
|---|---|---|---|---|
| 2023 | 8,760 | 8,760 | 105,120 | 105,120 |
| 2024 | 8,784 | 8,784 | 105,408 | 105,408 |
| 2025 | 8,760 | 8,760 | 105,120 | 105,120 |

12 generation sources in long format.

## 1a. Null keys

- generation.timestamp_utc: **0**
- generation.timestamp_local: **0**
- generation.source: **0**
- price_load.timestamp_utc: **0**
- price_load.timestamp_local: **0**

## 1b. Timestamp continuity and frequency

- gaps > 1 h: **0**
- non-increasing steps: **0**
- timestamps not on a full hour: **0**

## 2. Daylight saving time

Local days with ≠ 24 hours (expected: last Sunday in March = 23h, October = 25h):

| local_date | hours |
|---|---|
| 2023-03-26 | 23 |
| 2023-10-29 | 25 |
| 2024-03-31 | 23 |
| 2024-10-27 | 25 |
| 2025-03-30 | 23 |
| 2025-10-26 | 25 |

All irregular days are DST switch days: **True**.

## 3. Missing hours per year

| series | 2023 | 2024 | 2025 |
|---|---|---|---|
| biomass | 0 | 0 | 1 |
| hard_coal | 0 | 0 | 0 |
| hydro | 0 | 1 | 6 |
| lignite | 0 | 0 | 0 |
| natural_gas | 0 | 0 | 1 |
| nuclear | 0 | 8,076 | 8,760 |
| other_conventional | 0 | 3 | 6 |
| other_renewable | 0 | 0 | 0 |
| pumped_storage | 0 | 0 | 0 |
| solar | 0 | 0 | 1 |
| wind_offshore | 0 | 0 | 0 |
| wind_onshore | 0 | 0 | 1 |
| price_eur_mwh | 0 | 0 | 0 |
| consumption_mwh | 0 | 0 | 0 |

**Nuclear:** last hour with generation > 0 is 2023-04-15 23:00:00 (local). Germany shut down its last reactors on 2023-04-15; afterwards SMARD mostly reports no value. These NaNs are expected and are *not* filled.

## 4. Duplicates

- generation (timestamp_utc, source): **0**
- price_load (timestamp_utc): **0**

Raw quarter-hour chunks (non-numeric values like '-' are coerced to NaN and counted):

| name | duplicate_timestamps | conflicting_duplicates | non_numeric_values |
|---|---|---|---|
| lignite | 0 | 0 | 0 |
| nuclear | 0 | 0 | 0 |
| wind_offshore | 0 | 0 | 0 |
| hydro | 0 | 0 | 0 |
| other_conventional | 0 | 0 | 0 |
| other_renewable | 0 | 0 | 0 |
| biomass | 0 | 0 | 0 |
| wind_onshore | 0 | 0 | 0 |
| solar | 0 | 0 | 0 |
| hard_coal | 0 | 0 | 0 |
| pumped_storage | 0 | 0 | 0 |
| natural_gas | 0 | 0 | 0 |
| grid_load | 0 | 0 | 0 |
| day_ahead_price | 0 | 0 | 0 |

## 5. Negative generation

No negative generation values.

## 5a. Grid load range

Observed min / max hourly load: **31,278 / 76,400 MWh**. Hours outside [15,000, 120,000]: **0**.

## 6. Price plausibility and outliers

| year | hours | mean | median | min | max | negative_hours |
|---|---|---|---|---|---|---|
| 2023 | 8,760 | 95.18 | 98.02 | -500.00 | 524.27 | 301 |
| 2024 | 8,784 | 78.51 | 79.59 | -135.45 | 936.28 | 457 |
| 2025 | 8,760 | 89.32 | 92.43 | -250.32 | 583.40 | 576 |

- Outside harmonised limits [-500, 4000] EUR/MWh: **0**
- IQR outliers (outside [-78.67, 256.70], factor 3.0): **184** hours – kept, since price spikes and negative prices are real market outcomes and the focus of this analysis.

Five highest hours:

| timestamp_local | price_eur_mwh |
|---|---|
| 2024-12-12 17:00:00 | 936.28 |
| 2024-11-06 17:00:00 | 820.11 |
| 2024-12-12 16:00:00 | 818.98 |
| 2024-11-06 18:00:00 | 805.08 |
| 2024-12-12 18:00:00 | 674.18 |

Five lowest hours:

| timestamp_local | price_eur_mwh |
|---|---|
| 2023-07-02 14:00:00 | -500.00 |
| 2023-07-02 15:00:00 | -399.00 |
| 2023-07-02 13:00:00 | -266.92 |
| 2025-05-11 13:00:00 | -250.32 |
| 2025-05-11 14:00:00 | -230.98 |

## 7. Reconciliation with SMARD hourly series

Our hourly values (aggregated from quarter-hours) vs. SMARD's own hourly series. Tolerance: 0.1 MWh for volumes, 0.01 EUR/MWh for prices.

| series | compared_hours | max_abs_diff | mismatches | value_on_one_side_only |
|---|---|---|---|---|
| biomass | 26,303 | 0.02 | 0 | 1 |
| day_ahead_price | 26,304 | 0.01 | 0 | 0 |
| grid_load | 26,304 | 0.02 | 0 | 0 |
| hard_coal | 26,304 | 0.02 | 0 | 0 |
| hydro | 26,297 | 0.02 | 0 | 1 |
| lignite | 26,304 | 0.02 | 0 | 0 |
| natural_gas | 26,303 | 0.02 | 0 | 1 |
| nuclear | 9,468 | 0.00 | 0 | 0 |
| other_conventional | 26,295 | 0.02 | 0 | 6 |
| other_renewable | 26,304 | 0.02 | 0 | 0 |
| pumped_storage | 26,304 | 0.02 | 0 | 0 |
| solar | 26,303 | 0.02 | 0 | 1 |
| wind_offshore | 26,304 | 0.02 | 0 | 0 |
| wind_onshore | 26,303 | 0.02 | 0 | 1 |

## 8. Resolution detection

Raw data was downloaded in quarter-hour resolution. `step_minutes` is the most frequent gap between timestamps. For the price, `effective_15min_from` is the first local date on which the four quarter-hour prices of an hour differ, i.e. when the day-ahead market switched to 15-minute products. Before that, SMARD repeats the hourly price in each quarter.

Aggregation: volumes are summed, prices averaged (unweighted). An hour is only built if all 4 quarters exist, otherwise it stays NaN.

| name | step_minutes | raw_points | null_quarters | incomplete_hours | effective_15min_from |
|---|---|---|---|---|---|
| lignite | 15.00 | 105,216 | 0 | 0 | – |
| nuclear | 15.00 | 38,400 | 526 | 1 | – |
| wind_offshore | 15.00 | 105,216 | 0 | 0 | – |
| hydro | 15.00 | 105,216 | 23 | 2 | – |
| other_conventional | 15.00 | 105,216 | 19 | 7 | – |
| other_renewable | 15.00 | 105,216 | 0 | 0 | – |
| biomass | 15.00 | 105,216 | 1 | 1 | – |
| wind_onshore | 15.00 | 105,216 | 1 | 1 | – |
| solar | 15.00 | 105,216 | 1 | 1 | – |
| hard_coal | 15.00 | 105,216 | 0 | 0 | – |
| pumped_storage | 15.00 | 105,216 | 0 | 0 | – |
| natural_gas | 15.00 | 105,216 | 1 | 1 | – |
| grid_load | 15.00 | 105,216 | 0 | 0 | – |
| day_ahead_price | 15.00 | 105,216 | 0 | 0 | 2025-10-01 |

## 9. Plausibility: generation vs. grid load

Totals in TWh. A ratio below 1 is plausible since Germany has been a net importer since 2023; the gap also includes storage and measurement differences.

| year | generation_twh | grid_load_twh | generation_to_load |
|---|---|---|---|
| 2023 | 454.70 | 463.08 | 0.98 |
| 2024 | 438.93 | 470.40 | 0.93 |
| 2025 | 439.26 | 470.66 | 0.93 |
