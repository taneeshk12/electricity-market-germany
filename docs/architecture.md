# Architecture

```mermaid
flowchart LR
    subgraph Source
        S[("SMARD.de<br/>chart-data JSON API<br/>Bundesnetzagentur")]
    end
    subgraph Python["Python ETL (run_pipeline.py)"]
        E["extract.py<br/>weekly chunks, cached,<br/>retries"]
        T["transform.py<br/>UTC grid, DST,<br/>15 min → hourly"]
        Q["quality_checks.py<br/>9 checks,<br/>stops on critical"]
        L["load.py<br/>COPY → staging →<br/>upsert, 1 transaction"]
        V["warehouse_checks.py<br/>post-load verify"]
        A["run_analysis.py<br/>runs sql/analysis"]
    end
    subgraph Storage
        R[/"data/raw<br/>JSON (as delivered)"/]
        P[/"data/processed<br/>parquet"/]
        DB[("PostgreSQL 16<br/>(Docker)<br/>star schema")]
    end
    subgraph Outputs
        QR["docs/data_quality_report.md/.json"]
        VR["docs/warehouse_quality_report.md/.json"]
        DBT["dbt_electricity<br/>staging → marts"]
        AR["docs/analysis_results.md + CSV"]
        PBI["Power BI Desktop<br/>3-page report"]
    end

    S --> E --> R --> T --> P --> Q --> L --> DB
    Q --> QR
    DB --> V --> VR
    DB --> A --> AR
    DB --> DBT
    DB --> PBI
```

## Steps

| Step | What it does | Idempotency |
|---|---|---|
| **extract** | Downloads 14 SMARD series (12 generation sources, grid load, DE-LU day-ahead price) in quarter-hour resolution, plus SMARD's hourly series for reconciliation. Writes chunks atomically; records provenance in `manifest.json`. | Chunks already on disk are skipped. |
| **transform** | Keys everything on UTC hours, derives Europe/Berlin local time + UTC offset, detects the resolution, sums volumes / averages prices to hours (only complete hours), reshapes generation to long format. | Pure function of the raw files. |
| **quality** | Row counts, DST days, missing hours, duplicates, negative generation, price limits and outliers, reconciliation against SMARD hourly values, resolution detection, generation-vs-load balance. Also NULL keys, hourly continuity/frequency and grid-load range. Writes markdown + JSON (one record per check with expected/actual/status/timestamp), fails on critical issues. | Read-only. |
| **load** | Applies DDL, fills `dim_date` (holidays cross-checked with the Python `holidays` package), syncs `dim_datetime` and both facts via COPY + `INSERT … ON CONFLICT` + stale-row delete. | Re-run changes 0 rows; failure rolls back. |
| **verify** | Read-only checks on the loaded warehouse: row counts vs. processed files, orphans, date/hour keys consistent with `dim_datetime`, hourly gaps, calendar coverage, NULL price/load, per-hour source completeness. Fails the pipeline on critical issues. | Read-only (`SET TRANSACTION READ ONLY`). |
| **analysis** | Executes every `sql/analysis/*.sql`, saves CSV + markdown. | Read-only. |

## Key design decisions

1. **JSON API instead of the CSV portal.** It can be automated and delivers epoch timestamps and plain numbers,
   which avoids German number formats (`1.234,5`), `;` separators and ambiguous local timestamps.
2. **UTC as the primary time key.** A DST day becomes 23 or 25 consecutive UTC hours, with no special cases.
   Local date and hour are reporting attributes only.
3. **Download quarter-hours, aggregate ourselves, reconcile against SMARD.** This makes the resolution change
   visible (15-minute day-ahead prices from 2025-10-01) and proves the aggregation is correct (0 mismatches).
4. **Never fill missing data.** Incomplete hours stay NULL and rows without a value are not loaded. Every gap
   is listed in the quality report.
5. **Two fact tables.** Generation is per hour × source and price/load is per hour, so mixing them would
   duplicate prices 12 times.

6. **Quality gates before and after the load.** `quality` checks the processed files before anything is written;
   `verify` checks what actually arrived in PostgreSQL. Both write machine-readable JSON and stop the pipeline on
   critical failures.
7. **dbt as a separate layer.** dbt reads `public` and writes only to `staging`, `intermediate` and `marts`, from its
   own virtualenv. The Python pipeline and Power BI do not depend on it. See
   [`dbt_electricity/README.md`](../dbt_electricity/README.md).
