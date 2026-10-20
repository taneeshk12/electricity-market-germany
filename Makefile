# Convenience commands. Run `make help` for an overview.
# Pipeline targets (extract / transform / load / checks) are added in later phases.

PYTHON ?= python3.11
VENV   := .venv
PY     := $(VENV)/bin/python

-include .env
export

.PHONY: help venv db-up db-down db-reset db-shell db-logs

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

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
