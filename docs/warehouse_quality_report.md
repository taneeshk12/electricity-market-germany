# Warehouse quality report

Generated: 2026-11-12 12:56 UTC by `src/warehouse_checks.py` (read-only checks on the PostgreSQL star schema after `load`). Period 2023-01-01 – 2025-12-31.

**Status: passed_with_warnings** · 17 pass · 1 warn · 0 fail

Machine-readable version: [`warehouse_quality_report.json`](warehouse_quality_report.json).

| check | description | expected | actual | severity | status |
|---|---|---|---|---|---|
| row_count.fact_hourly | fact_hourly rows = non-null generation rows in the parquet file | 298792 | 298792 | critical | ✅ pass |
| row_count.fact_price_load | fact_price_load rows = rows in the parquet file | 26304 | 26304 | critical | ✅ pass |
| row_count.dim_datetime | dim_datetime has one row per hour of the period | 26304 | 26304 | critical | ✅ pass |
| row_count.dim_hour | dim_hour has 24 rows | 24 | 24 | critical | ✅ pass |
| row_count.dim_source | dim_source covers every pipeline source | >= 12 | 12 | critical | ✅ pass |
| orphans.fact_hourly.timestamp_key | fact_hourly rows without a dim_datetime row | 0 | 0 | critical | ✅ pass |
| orphans.fact_hourly.source_key | fact_hourly rows without a dim_source row | 0 | 0 | critical | ✅ pass |
| orphans.fact_hourly.date_key | fact_hourly rows without a dim_date row | 0 | 0 | critical | ✅ pass |
| orphans.fact_price_load.timestamp_key | fact_price_load rows without a dim_datetime row | 0 | 0 | critical | ✅ pass |
| orphans.dim_datetime.date_key | dim_datetime rows without a dim_date row | 0 | 0 | critical | ✅ pass |
| key_consistency.fact_hourly | fact_hourly date_key/hour_key agree with dim_datetime | 0 | 0 | critical | ✅ pass |
| key_consistency.fact_price_load | fact_price_load date_key/hour_key agree with dim_datetime | 0 | 0 | critical | ✅ pass |
| hours_without_price_load | every dim_datetime hour has a fact_price_load row | 0 | 0 | critical | ✅ pass |
| hourly_gaps.dim_datetime | consecutive dim_datetime hours are exactly 1 hour apart | 0 | 0 | critical | ✅ pass |
| local_dates_missing_in_dim_date | every local date of the period exists in dim_date | 0 | 0 | critical | ✅ pass |
| null_price_or_load | no NULL price or grid load in fact_price_load | 0 | 0 | critical | ✅ pass |
| range.generation_non_negative | generation_mwh >= 0 | 0 | 0 | critical | ✅ pass |
| completeness.sources_per_hour | hours where a non-nuclear source has no value | 0 | 15 | warning | ⚠️ warn |
