# Interview Bot — backend developer tasks.
# `make test` is the offline fast tier: no API keys, no network, no database.

PY ?= python
# The offline gate forces replay mode and blanks provider keys so nothing can
# accidentally reach the network.
OFFLINE_ENV = TRANSPORT_MODE=replay LANGFUSE_ENABLED=false \
	ANTHROPIC_API_KEY= GEMINI_API_KEY= VOYAGE_API_KEY= DEEPGRAM_API_KEY=

.PHONY: install dev test test-fast lint typecheck contracts eval eval-generator record fmt

install:  ## Install the package + dev tooling into the active environment
	$(PY) -m pip install -e . -r requirements-dev.txt

dev:  ## Run the API with autoreload (needs DATABASE_URL + a provider key)
	uvicorn interview_bot.api.app:app --reload --host 0.0.0.0 --port 8000

test: lint typecheck contracts test-fast  ## Full offline gate (what CI runs)

test-fast:  ## Unit + contract tests, offline under replay
	$(OFFLINE_ENV) $(PY) -m pytest -q

lint:  ## Ruff lint
	$(PY) -m ruff check src tests fixtures scripts evals

typecheck:  ## Mypy on the package
	$(PY) -m mypy src

contracts:  ## Enforce the dependency rule (import-linter)
	$(PY) -m importlinter.cli lint || lint-imports

fmt:  ## Auto-fix lint + import order
	$(PY) -m ruff check --fix src tests fixtures scripts evals

eval:  ## Run the scorer eval over the golden set (REQUIRES provider API keys)
	$(PY) -m evals.run_scorer_eval

eval-generator:  ## Run the generator eval over the golden set (REQUIRES provider API keys)
	$(PY) -m evals.run_generator_eval

record:  ## Re-record cassettes against the live provider APIs (REQUIRES keys)
	TRANSPORT_MODE=record $(PY) scripts/record_cassettes.py
