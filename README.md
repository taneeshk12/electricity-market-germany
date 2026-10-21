# What drives electricity prices in Germany?

**Renewables, demand and negative prices (2023–2025)**

> 🚧 Work in progress. Sections marked *TBD* get filled in once the analysis is done, using numbers from the actual query results only.

## Business questions

1. How has the share of renewables (wind, solar, etc.) developed over time?
2. How strongly does renewable generation affect the day-ahead price?
3. When and why do negative prices occur (hour, weekday, season, holidays)?
4. What does a typical day look like in summer vs. winter?

## Data source

[SMARD.de](https://www.smard.de) – Strommarktdaten der Bundesnetzagentur, market area DE/LU:
actual generation by source, actual consumption (grid load), day-ahead prices.
Period: 2023-01-01 – 2025-12-31.

Data source: **Bundesnetzagentur | SMARD.de**. Raw data is not redistributed in this repository; the pipeline downloads it from SMARD. *Full terms of use: TBD (Phase 6).*

## Architecture

*TBD – Mermaid diagram (Phase 6).*

```
SMARD  →  extract.py  →  transform.py  →  quality_checks.py  →  load.py  →  PostgreSQL (star schema)  →  Power BI
```

## Tech stack

Python 3.11 · pandas · SQLAlchemy · PostgreSQL 16 (Docker) · Power BI Desktop

## Quick start

```bash
cp .env.example .env          # then set a password
make venv                     # create .venv and install requirements
make db-up                    # start PostgreSQL 16 on localhost:5433
make db-shell                 # optional: open psql
make pipeline                 # extract -> transform -> quality checks -> load into PostgreSQL
```

## Repository structure

```
data/raw/           original SMARD files (gitignored)
data/processed/     cleaned hourly data (gitignored)
src/                extract → transform → quality checks → load
sql/                schema DDL, date dimension, analysis queries
powerbi/            DAX measures and report specification
docs/               architecture, data model, data quality report
```

## Key findings

*TBD (Phase 6).*

## Limitations & next steps

*TBD (Phase 6).*
