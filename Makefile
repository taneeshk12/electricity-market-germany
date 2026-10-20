# Convenience commands. Run `make help` for an overview.
# Pipeline targets (extract / transform / load / checks) are added in later phases.

PYTHON ?= python3.11
VENV   := .venv
PY     := $(VENV)/bin/python

-include .env
export

.DEFAULT_GOAL := help

.PHONY: help venv db-up db-down db-reset db-shell db-logs pipeline extract transform quality load analysis

pipeline:  ## Run the full pipeline (extract -> transform -> quality -> load -> analysis)
	$(PY) run_pipeline.py

extract:  ## Download raw SMARD data (skips chunks already on disk)
	$(PY) run_pipeline.py --steps extract

transform:  ## Clean + aggregate raw data to hourly parquet files
	$(PY) run_pipeline.py --steps transform

quality:  ## Run data quality checks -> docs/data_quality_report.md
	$(PY) run_pipeline.py --steps quality

load:  ## Load processed data into the PostgreSQL star schema (idempotent)
	$(PY) run_pipeline.py --steps load

analysis:  ## Run sql/analysis/*.sql -> docs/analysis_results.md
	$(PY) run_pipeline.py --steps analysis

help:  ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

venv:  ## Create virtualenv and install dependencies
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

db-up:  ## Start PostgreSQL and wait until it is healthy
	docker compose up -d --wait

db-down:  ## Stop PostgreSQL (data volume is kept)
	docker compose down

db-reset:  ## Stop PostgreSQL AND delete its data volume
	docker compose down -v

db-shell:  ## Open psql inside the container
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-logs:  ## Tail database logs
	docker compose logs -f db
