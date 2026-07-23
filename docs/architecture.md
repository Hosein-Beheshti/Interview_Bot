# Architecture

Python backend for an AI interview / candidate-evaluation agent: CV ingestion →
structured extraction → per-competency rubric scoring → recommendation, driven by
an FSM interview loop over a provider abstraction (Anthropic / Gemini), with a
record/replay determinism seam and a first-class eval harness.

## The dependency rule

**Pure core, imperative shell.** Dependencies point inward. The `domain/` layer
is pure — no network, I/O, clock, config, or SDKs — so the highest-signal logic
(rubric scoring, the FSM, aggregation) is trivially findable and mock-free
testable. This is enforced mechanically by **import-linter** (`make contracts`),
not by convention:

- `domain/` imports nothing from `prompts`, `llm`, `pipeline`, `api`,
  `persistence`, `telemetry`, `integrations`, `retrieval`, or even `config`.
- `prompts/` may import `domain` only.
- `llm/` (the transport waist) never imports `pipeline`/`api`.

Arrows: `api → pipeline → {domain, prompts, llm, retrieval, persistence}`;
`llm → telemetry`.

## Module map

Each concept has a consistent filename across the layers it touches, so its code
is findable by name: `scoring`, `profile`, `plan`, `interview`, `cv`.

| Module | Responsibility | Depends on |
|---|---|---|
| `domain/progression` | Interview FSM: `decide_next_turn`, `apply_turn`. `max_followups` passed in. | (pure) |
| `domain/rubric` | Rubric definition, score schema, weighted overall, `RUBRIC_VERSION` | (pure) |
| `domain/scoring` | `ScoreData` + `parse_score` (validate model output) | rubric |
| `domain/profile` | `JobProfile`, normalization, prompt-ready context | (pure) |
| `domain/plan` | `InterviewPlan`/`PlanSlot`, normalization | profile |
| `domain/summary` | Result aggregation | (pure) |
| `prompts/interviewer` | Interviewer prompt rendering; re-exports FSM modes | domain |
| `prompts/scoring` | Scorer system prompt, cache prefix, `PROMPT_VERSION` | domain.rubric |
| `prompts/profile`, `prompts/plan` | Extraction system prompts + LLM I/O models | domain |
| `llm/__init__` | Facade: `generate` / `generate_structured` / `parse` | transport, registry, telemetry |
| `llm/transport` | **Record/replay waist** — every provider call funnels here | config, telemetry |
| `llm/provider` + `anthropic`/`gemini`/`registry` | `LLMProvider` ABC + 2 adapters + factory | SDKs, config |
| `integrations/{embeddings,speech,cv_parser}` | Voyage / Deepgram / CV text extraction | transport, config |
| `retrieval/rag` | Chunk → embed → pgvector search | integrations, persistence |
| `retrieval/cv_context` | Full-text-vs-retrieval policy for the turn | rag, config |
| `pipeline/interview` | Run one turn: score → decide → generate | llm, domain, prompts, pipeline.scoring, retrieval |
| `pipeline/scoring` | `score` / `score_answer`: assemble scorer prompt, call, parse | llm, domain, prompts |
| `pipeline/profile`, `pipeline/plan` | Extraction calls (job profile, blueprint) | llm, domain, prompts |
| `pipeline/session` | Session setup flow (compose extraction + persist) | pipeline.{profile,plan}, persistence |
| `api/app` + `routes/*` + `schemas` | FastAPI app, endpoints, DTOs | pipeline, persistence |
| `persistence/*` | Engine, ORM models (typed `Mapped`), migrations, vector store, `sessions` CRUD | config |
| `telemetry/*` | Tracing seam (Noop + Langfuse backends) | config |
| `config` | Single validated settings object; only home of env | — |

No import cycles. `os.getenv` appears only in `config.py`.

> **Prompt bytes note:** a Pydantic extraction model's *docstring* is emitted as
> its JSON-schema `description` and is therefore part of the assembled `llm.parse`
> request — editing it changes the frozen prompt bytes. The extraction models in
> `prompts/{profile,plan}.py` carry a comment saying so.

## The determinism story

The one hard invariant: **given identical inputs and identical recorded LLM
responses, the system produces byte-identical outputs — and the assembled prompt
bytes are themselves outputs.**

1. **The seam.** `llm/transport.py::call()` is the single waist every
   model-provider call passes through (LLM, embeddings, speech). Modes:
   `live` (default), `record` (call + persist a cassette), `replay` (serve from
   disk; no network, no keys). The request dict is canonicalized (sorted-key
   compact JSON) and SHA-256 hashed — the hash is the cassette identity.
2. **Cassettes** (`backend/cassettes/`) capture request, response, latency, and
   token usage. Recorded by `scripts/record_cassettes.py` over 3 synthetic CVs /
   roles (`fixtures/`), covering full pipelines and distinct FSM trajectories.
3. **Contract tests** (`tests/contract/`) run everything under replay and assert:
   golden outputs (profile, plan, per-competency scores, summary) equal the
   committed recordings; exact assembled prompt bytes match snapshots; FSM
   trajectories and per-turn decisions match. All offline, in seconds. A prompt
   change misses its cassette *and* fails the snapshot — loudly, on purpose.

## The versioning story

Prompts and rubrics are versioned artifacts; results across versions are not
comparable. `PROMPT_VERSION` (scoring prompt + output schema) and `RUBRIC_VERSION`
(rubric definition) are **content-derived hashes**, so they change automatically
when their source changes — impossible to forget to bump. Every `score_answer`
call emits both on its trace (via `trace_metadata`), and the eval results artifact
records them. Versions ride on telemetry only, never in the frozen `ScoreData` or
API response, so the behavior freeze holds.

## Decisions & tradeoffs

**Earned abstractions (a second implementation exists today):**
- `LLMProvider` ABC — two adapters (Anthropic, Gemini) behind one waist.
- `TracingBackend` / `Handle` ABCs — Noop + Langfuse.
- The record/replay transport — needed for offline determinism, the repo's spine.

**Abstractions deliberately declined:**
- No repository/UnitOfWork over SQLAlchemy — one DB, a direct session is clearer.
- No separate `rubrics/` package — the rubric is one small pure module; a package
  for one tuple is ceremony. It carries `RUBRIC_VERSION` in place.
- No provider factory beyond the existing registry, no DI container, no base
  class for routes. Each fails the "name the second implementation today" test.

**Simpler-over-architectural choices:**
- `progression` is a pure function taking `max_followups` as an argument, not a
  stateful policy object.
- The turn-mode constants live in the domain (the FSM's home) and are re-exported
  by `prompts`, so the domain imports nothing outward.
- The ORM uses typed `Mapped` columns so a persisted field reads as its Python
  type across the app — typed boundaries without a mapping layer.

**Known debt (frozen behavior — not fixed here):**
- `api/app.py` runs DDL at import time and uses the deprecated `on_event`
  shutdown hook; `datetime.utcnow` in the ORM is deprecated. CORS is `*`.
- `voice.py` returns the exception string to the client (minor info leak).
- `prompts.prompt.get_system_prompt` is now used only by tests.
