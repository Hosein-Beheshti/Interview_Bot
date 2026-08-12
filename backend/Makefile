# Interview Bot — backend developer tasks.
# `make test` is the offline fast tier: no API keys, no network, no database.

PY ?= python
# The offline gate forces replay mode and blanks provider keys so nothing can
# accidentally reach the network.
OFFLINE_ENV = TRANSPORT_MODE=replay LANGFUSE_ENABLED=false \
	ANTHROPIC_API_KEY= GEMINI_API_KEY= VOYAGE_API_KEY= DEEPGRAM_API_KEY=

# The everyday gate also allows a reworded interviewer prompt to replay the
# cassette for the same conversation, so prompt iteration doesn't cost an API
# run. `make test-strict` turns it off and demands exact-hash replay — that is
# the tier that actually proves the behavior freeze, and it is what CI runs
# before a release. See `cassette_fallback` in `config.py`.
FALLBACK_ENV = CASSETTE_FALLBACK=true

.PHONY: install dev test test-strict test-fast lint typecheck contracts \
	eval eval-generator record snapshots fmt

install:  ## Install the package + dev tooling into the active environment
	$(PY) -m pip install -e . -r requirements-dev.txt

dev:  ## Run the API with autoreload (needs DATABASE_URL + a provider key)
	uvicorn interview_bot.api.app:app --reload --host 0.0.0.0 --port 8000

test: lint typecheck contracts test-fast  ## Full offline gate (everyday)

test-strict: lint typecheck contracts  ## Exact-hash replay — proves the freeze
	$(OFFLINE_ENV) $(PY) -m pytest -q

test-fast:  ## Unit + contract tests, offline under replay
	$(OFFLINE_ENV) $(FALLBACK_ENV) $(PY) -m pytest -q

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

snapshots:  ## Accept the current prompt/output bytes as the new snapshots
	$(OFFLINE_ENV) $(FALLBACK_ENV) UPDATE_SNAPSHOTS=1 $(PY) -m pytest -q tests/contract
	@echo
	@echo "Snapshots rewritten. Review the diff — that diff IS the prompt change."
	@git -C .. diff --stat -- backend/tests/contract/snapshots
