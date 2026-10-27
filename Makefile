PY ?= python
export PYTHONPATH := src

.PHONY: setup up down lint test test-integration demo serve clean

setup:
	$(PY) -m pip install -r requirements.txt

# SQL Server, PostgreSQL and MongoDB in containers (see .env.example for the connection strings)
up:
	docker compose up -d

down:
	docker compose down -v

lint:
	ruff check .
	ruff format --check .

# Business rules and mapping, no database needed
test:
	$(PY) -m pytest -q tests/unit

# Full scenario against the three databases
test-integration:
	$(PY) -m pytest -q tests/integration

# Synthetic legacy data -> full load -> a day of legacy activity -> incremental load
demo:
	$(PY) -m migration reset-target
	$(PY) -m migration seed --scale 1
	$(PY) -m migration run --mode full
	$(PY) -m migration changes
	$(PY) -m migration run --mode incremental
	@cat reports/latest.md

serve:
	$(PY) -m migration serve

clean:
	rm -rf reports .pytest_cache .ruff_cache
