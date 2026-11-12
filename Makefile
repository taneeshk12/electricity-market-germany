# Convenience commands. Run `make help` for an overview.

PYTHON ?= python3.11
VENV   := .venv
PY     := $(VENV)/bin/python
DBT_VENV := .venv-dbt
DBT      := cd dbt_electricity && ../$(DBT_VENV)/bin/dbt
DBT_ARGS := --profiles-dir . --project-dir .

-include .env
export

.DEFAULT_GOAL := help

.PHONY: help venv install db-up db-down db-reset db-shell db-logs up down \
        pipeline extract transform quality load verify analysis \
        test test-unit test-integration lint format \
        dbt-venv dbt-profile dbt-debug dbt-build dbt-test dbt-docs dbt-docs-serve \
        agent-role agent-check agent-metrics mcp-server app

pipeline:  ## Run the full pipeline (extract -> transform -> quality -> load -> verify -> analysis)
	$(PY) run_pipeline.py

extract:  ## Download raw SMARD data (skips chunks already on disk)
	$(PY) run_pipeline.py --steps extract

transform:  ## Clean + aggregate raw data to hourly parquet files
	$(PY) run_pipeline.py --steps transform

quality:  ## Run data quality checks -> docs/data_quality_report.md/.json
	$(PY) run_pipeline.py --steps quality

load:  ## Load processed data into the PostgreSQL star schema (idempotent)
	$(PY) run_pipeline.py --steps load

verify:  ## Read-only post-load warehouse checks -> docs/warehouse_quality_report.md/.json
	$(PY) run_pipeline.py --steps verify

analysis:  ## Run sql/analysis/*.sql -> docs/analysis_results.md
	$(PY) run_pipeline.py --steps analysis

help:  ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

venv:  ## Create virtualenv and install runtime dependencies
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

install: venv  ## venv + development tools (pytest, ruff)
	$(PY) -m pip install -r requirements-dev.txt

# --- Database -------------------------------------------------------------------------

db-up:  ## Start PostgreSQL and wait until it is healthy
	docker compose up -d --wait

db-down:  ## Stop PostgreSQL (data volume is kept)
	docker compose down

up: db-up  ## Alias for db-up

down: db-down  ## Alias for db-down (keeps data)

db-reset:  ## Stop PostgreSQL AND delete its data volume
	docker compose down -v

db-shell:  ## Open psql inside the container
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-logs:  ## Tail database logs
	docker compose logs -f db

# --- Quality gates ---------------------------------------------------------------------

test-unit:  ## Unit tests (no database, no network)
	$(PY) -m pytest tests/unit

# Integration tests create and drop a throwaway emg_test_* database on the local server;
# the pipeline database is never touched. `@` keeps the password out of the terminal.
test-integration:  ## Integration tests against PostgreSQL (needs `make db-up`)
	@TEST_PG_ADMIN_URL="postgresql+psycopg2://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/postgres" \
		$(PY) -m pytest tests/integration

test:  ## All tests with coverage (needs `make db-up`)
	@TEST_PG_ADMIN_URL="postgresql+psycopg2://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/postgres" \
		$(PY) -m pytest --cov=src --cov=analytics_agent --cov-report=term-missing

lint:  ## Ruff lint + format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format:  ## Auto-fix lint issues and format code
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

# --- dbt (separate virtualenv, builds into schemas staging / intermediate / marts) -----

dbt-venv:  ## Create .venv-dbt with dbt-core + dbt-postgres
	$(PYTHON) -m venv $(DBT_VENV)
	$(DBT_VENV)/bin/pip install --upgrade pip
	$(DBT_VENV)/bin/pip install -r requirements-dbt.txt

dbt-profile:  ## Create dbt_electricity/profiles.yml from the example (reads credentials from .env)
	@test -f dbt_electricity/profiles.yml || cp dbt_electricity/profiles.example.yml dbt_electricity/profiles.yml

dbt-debug: dbt-profile  ## Check the dbt connection
	$(DBT) debug $(DBT_ARGS)

dbt-build: dbt-profile  ## Build all dbt models and run all dbt tests
	$(DBT) build $(DBT_ARGS)

dbt-test: dbt-profile  ## Run dbt tests only
	$(DBT) test $(DBT_ARGS)

dbt-docs: dbt-profile  ## Generate dbt documentation (target/index.html)
	$(DBT) docs generate $(DBT_ARGS)

dbt-docs-serve: dbt-docs  ## Serve dbt docs on http://localhost:8080
	$(DBT) docs serve $(DBT_ARGS) --port 8080

# --- Analytics agent ---------------------------------------------------------------------

agent-role:  ## Create/update the read-only DB role for the agent (uses admin creds from .env)
	$(PY) -m analytics_agent.db_role

agent-check:  ## Verify schema context and read-only permissions against the live DB
	$(PY) -m analytics_agent.cli --check

agent-metrics:  ## Run every metric example as the agent role -> docs/metric_catalogue.md
	$(PY) -m analytics_agent.cli --verify-metrics

mcp-server:  ## Run the MCP server on stdio (for MCP clients / inspector)
	$(PY) -m analytics_agent.server

app:  ## Start the Streamlit app on http://localhost:8501
	$(VENV)/bin/streamlit run app/streamlit_app.py
