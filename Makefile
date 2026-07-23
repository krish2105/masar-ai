# =============================================================================
# MASAR AI
# =============================================================================
.DEFAULT_GOAL := help
SHELL := /bin/bash

PY      := backend/.venv/bin/python
PIP     := backend/.venv/bin/pip
UVICORN := backend/.venv/bin/uvicorn
PYTEST  := backend/.venv/bin/pytest

.PHONY: help setup up up-full down logs ingest silver gold index etl eval test lint dev dev-api dev-web clean nuke

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup ----
setup: ## Create venv, install backend + frontend deps, seed .env
	@test -f .env || (cp .env.example .env && echo "→ created .env from template")
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip -q
	$(PIP) install -r backend/requirements.txt
	@cd frontend && npm install
	@echo "✓ setup complete — next: make up && make etl"

# ------------------------------------------------------------ services ----
up: ## Start postgres + redis
	docker compose up -d postgres redis
	@echo "→ waiting for healthchecks…"
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' masar-postgres 2>/dev/null)" = "healthy" ] \
	    && [ "$$(docker inspect -f '{{.State.Health.Status}}' masar-redis 2>/dev/null)" = "healthy" ]; \
	  do sleep 1; done
	@echo "✓ postgres + redis healthy"

up-full: ## Start the whole stack including the containerised API
	docker compose --profile full up -d --build

down: ## Stop all services (data volumes survive)
	docker compose --profile full down

logs: ## Tail service logs
	docker compose logs -f --tail=100

# ------------------------------------------------------------------ etl ----
ingest: ## Phase 1 — recover the 12 datasets into data/bronze/
	$(PY) -m backend.ingestion.run_bronze

silver: ## Phase 2 — type, normalise, dedupe → data/silver/ + DQ reports
	$(PY) -m backend.ingestion.run_silver

gold: ## Phase 3 — build the star schema and load it into Postgres
	$(PY) -m backend.ingestion.run_gold

index: ## Phase 4 — chunk, embed and build the hybrid search indexes
	$(PY) -m backend.retrieval.run_index

etl: ingest silver gold index ## Run the full offline pipeline end to end
	@echo "✓ lakehouse built — bronze → silver → gold → indexed"

# ----------------------------------------------------------------- eval ----
eval: ## Phase 10 — golden set + RAGAS metrics (fails below §8.2 thresholds)
	$(PY) -m backend.tests.golden.run_eval

ablation: ## Four-config ablation study → docs/EVALUATION.md
	$(PY) -m backend.tests.golden.run_ablation

# ----------------------------------------------------------- dev / test ----
test: ## Run the backend test suite
	$(PYTEST) backend/tests -q

lint: ## Ruff + mypy + tsc
	backend/.venv/bin/ruff check backend
	backend/.venv/bin/ruff format --check backend
	@cd frontend && npx tsc --noEmit

dev-api: ## Run the API with reload
	$(UVICORN) backend.main:app --reload --host 0.0.0.0 --port 8000

dev-web: ## Run the Next.js dev server
	cd frontend && npm run dev

dev: ## Run API + frontend together
	@$(MAKE) -j2 dev-api dev-web

# ---------------------------------------------------------------- clean ----
clean: ## Remove generated data and caches (keeps the curated corpus)
	rm -rf data/bronze/* data/silver/* data/gold/* reports/dq/* reports/eval/* traces/*
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

nuke: down clean ## clean + drop the database volumes
	docker volume rm -f masar_masar_pgdata masar_masar_redisdata 2>/dev/null || true
