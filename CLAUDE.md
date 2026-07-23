# Working in this repo

AI interview / candidate-evaluation agent. Python backend (`backend/src/interview_bot/`,
an installable package) + React frontend (`frontend/`). This file records the
constraints the backend was built to; keep to them.

## The behavior-freeze invariant

Given identical inputs **and identical recorded LLM responses**, the system
produces **byte-identical outputs**. Assembled prompts are outputs too — the exact
bytes sent to each provider must not change. Reordering a prompt section or
altering whitespace is a behavior change even if every structural test stays green.

- The safety net is `tests/contract/` (golden outputs, prompt snapshots, FSM
  trajectories) run under replay. **If a prompt snapshot test fails, stop and
  report it** — do not run `UPDATE_SNAPSHOTS=1` to make it pass unless the prompt
  change is intended.
- Where current behavior is buggy, the bug is preserved. Freeze behavior; log
  bugs, don't fix them silently. Known frozen debt is listed in
  `docs/architecture.md`.

## The dependency rule (enforced, not aspirational)

`domain/` is pure: no network, I/O, clock, config, or SDKs. Dependencies point
inward. Enforced by import-linter — run `make contracts` (or `lint-imports`).
Don't add an import that breaks a contract; if the design needs it, move the code,
don't weaken the contract.

## Earn every abstraction

No new layers, interfaces, base classes, factories, registries, or DI unless a
second concrete implementation exists **today** or a specific near-term change
needs it. Prefer: plain function → module of functions → dataclass/Pydantic model
→ class with state → Protocol/ABC with multiple impls. Advance one step only when
the current one visibly breaks. `utils`/`helpers`/`manager`/`handler`/`common` are
banned names — reaching for one means the responsibility isn't defined yet.

## Determinism & versioning

- Every model-provider call must go through the `llm/transport.py` waist. Don't
  call a provider SDK from anywhere else.
- Prompts and rubrics are versioned artifacts (`PROMPT_VERSION`, `RUBRIC_VERSION`,
  content-derived). Every scoring result must be traceable to them. Versions ride
  on telemetry, never in the frozen output.
- After changing anything under `src/`, run the gate: `make test` (ruff + mypy +
  import-linter + pytest under replay). It must be green, offline, in seconds.
- To change a prompt on purpose: edit it, re-record cassettes
  (`make record`, needs keys) or update the affected snapshot deliberately, and
  say so in the commit.

## Conventions

- One config surface: no `os.getenv` outside `config.py`.
- Pydantic at every process boundary (HTTP, LLM output, persistence); no raw dicts
  across module lines.
- Backend changes only unless asked otherwise. If a change would require a
  frontend edit, stop and say so.
- Commits: conventional-commit style, one logical change, repo green after each.
  **Do not add AI/Claude/Anthropic co-author or attribution lines to commits.**
