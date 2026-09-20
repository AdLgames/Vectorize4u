# Repo-level entry points. Everything here must work offline: the engine is a
# pure library and has to stay testable and benchmarkable without a service.

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
ENGINE := packages/engine

.PHONY: help setup fixtures test lint typecheck check bench bench-baseline ab ab-report clean

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

fixtures: ## (re)generate the synthetic corpus
	$(PY) benchmarks/fixtures.py

test: ## run the engine test suite with coverage (§11 gate: >= 80%)
	cd $(ENGINE) && ../../$(PY) -m pytest tests -q \
	  --cov=engine --cov-report=term-missing --cov-fail-under=80

lint: ## ruff
	$(PY) -m ruff check $(ENGINE) benchmarks

format: ## ruff --fix
	$(PY) -m ruff check --fix $(ENGINE) benchmarks

typecheck: ## mypy --strict on the engine
	cd $(ENGINE) && ../../$(PY) -m mypy engine

check: lint typecheck test ## everything CI runs except bench

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

clean:
	rm -rf benchmarks/ab/out benchmarks/out .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
