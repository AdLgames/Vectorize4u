# Repo-level entry points. Everything here must work offline: the engine is a
# pure library and has to stay testable and benchmarkable without a service.

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
ENGINE := packages/engine

.PHONY: help setup setup-service fixtures test test-api lint typecheck check bench \
        bench-baseline ab ab-report kit api worker web web-build web-lint e2e \
        stripe-bootstrap clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## create the venv and install the engine with dev extras
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e "$(ENGINE)[dev,emit]"
	@echo
	@echo "Tracer binaries are not pip-installable. See docs/runbook.md:"
	@echo "  cargo install vtracer resvg   # MIT"
	@echo "  apt-get install potrace       # GPLv2 — subprocess only"

setup-service: ## install the API and worker into the same venv
	$(PIP) install -e "apps/api[dev]" -e "apps/worker[dev]"

fixtures: ## (re)generate the synthetic corpus
	$(PY) benchmarks/fixtures.py

test: ## run the engine test suite with coverage (§11 gate: >= 80%)
	cd $(ENGINE) && ../../$(PY) -m pytest tests -q \
	  --cov=engine --cov-report=term-missing --cov-fail-under=80

test-api: ## run the service test suite (the real engine runs inside it)
	cd apps/api && ../../$(PY) -m pytest tests -q

lint: ## ruff
	$(PY) -m ruff check $(ENGINE) benchmarks apps/api apps/worker

format: ## ruff --fix
	$(PY) -m ruff check --fix $(ENGINE) benchmarks

typecheck: ## mypy --strict on the engine, the API and the worker
	cd $(ENGINE) && ../../$(PY) -m mypy engine
	cd apps/api && ../../$(PY) -m mypy app
	cd apps/worker && ../../$(PY) -m mypy worker

check: lint typecheck test test-api ## everything CI runs except bench

# The environment goes on the command that needs it, AFTER the cd:
# `VAR=x cd dir && cmd` scopes VAR to `cd` and cmd never sees it, which
# silently started the API with the worker disabled and dev sign-in off.
api: ## run the API locally with the worker inline (no Redis, no Postgres)
	cd apps/api && \
	  VEC_ENVIRONMENT=dev VEC_INLINE_WORKER=1 VEC_DEV_AUTH_ENABLED=1 \
	  VEC_DATABASE_URL="sqlite+pysqlite:///./dev.db" \
	  VEC_STORAGE_BACKEND=local VEC_STORAGE_LOCAL_DIR=./.storage \
	  ../../$(PY) -m uvicorn app.main:app --reload --port 8000

worker: ## run a real Celery worker against all three lanes
	cd apps/worker && ../../$(PY) -m celery -A worker.celery_app:celery_app worker \
	  -Q queue_preview,queue_sync,queue_batch \
	  --without-gossip --without-mingle --loglevel=info

web: ## run the Next.js dev server against a local API (dev sign-in on)
	cd apps/web && NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 \
	  NEXT_PUBLIC_DEV_AUTH=1 npm run dev

e2e: ## drive the app in a real browser (needs `make api` + `make web`)
	cd apps/web && npm install --no-save playwright \
	  && node e2e/smoke.mjs && node e2e/signed-in.mjs && node e2e/checkout.mjs

stripe-bootstrap: ## create this product's Stripe products and prices (idempotent)
	cd apps/api && ../../$(PY) scripts/bootstrap_stripe.py

web-build: ## production build of the web app
	cd apps/web && npm run build

web-lint: ## eslint + tsc for the web app
	cd apps/web && npm run lint && npm run typecheck

bench: ## per-category means + regression gate against benchmarks/baseline.json
	$(PY) benchmarks/run.py

bench-baseline: ## regenerate baseline.json (same PR as any score_version bump)
	$(PY) benchmarks/run.py --write-baseline

ab: ## build the blind A/B page (this, not bench, is the kill-switch evidence)
	$(PY) benchmarks/ab/make_ab.py --comparator vtracer-default

ab-external: ## blind A/B against SVGs in benchmarks/ab/external/
	$(PY) benchmarks/ab/make_ab.py --comparator external

ab-report: ## apply the §12 kill switch to benchmarks/ab/votes.json
	$(PY) benchmarks/ab/report.py

kit: ## build + self-verify the cut-correctness acceptance kit (§13)
	$(PY) benchmarks/acceptance/make_kit.py

clean:
	rm -rf benchmarks/ab/out benchmarks/acceptance/out benchmarks/out .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
