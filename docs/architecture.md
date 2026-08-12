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
| `domain/progression` | Interview FSM: `decide_next_turn`, `apply_turn`. `max_followups` passed in; `answered` separates "no answer yet" from "answer we could not grade". | (pure) |
| `domain/turn_quality` | Judge criteria, plus the `check_format` / `repair` label contract enforced on every live turn | progression |
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

## Measuring the system on real traffic

`InterviewSession.scores` holds only the roll-up the candidate is shown — enough
to render a result, not enough to tell whether the scoring is any good. Every
graded answer is therefore also written to `answer_scores` (`persistence/models`),
with the per-dimension scores, the answer classification, the evaluator's
critique, and the `(prompt_version, rubric_version, model)` triple it is only
comparable within. Nothing in the request path reads it; it exists so scorer drift
can be measured on real interviews rather than only on a 38-item golden set. It
cascades with the session, so both the retention sweep and an explicit delete
erase it.

Turn generation can run on a different model from everything else
(`settings.generator_model`, empty = use `model`). Generation is the only output a
candidate reads and the place a small model's drift shows; scoring, judging, and
extraction are schema-constrained and stay on the default. The model name is part
of a request's replay identity, so changing it needs `make record`.

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

**Server owns control, the model owns language — including the ending.** The FSM
decides every transition; the interviewer model only phrases questions. The
*closing* turn is fully server-owned: it is rendered deterministically from the
results (`domain.summary.closing_message`), not generated, so it can neither ask a
dangling question nor be derailed by an instruction injected into an answer. Only
the two model-driven modes (main question, follow-up) reach `turn_instruction`.

**…and the server owns the label, too.** Being authoritative about progression is
not enough if the text the candidate reads disagrees with it. `turn_quality.repair`
runs on every generated turn: a main question gets the number the server says it
is, and a follow-up cannot present itself as a new numbered question. It is pure
string work, not a retry — a regeneration would send byte-identical request bytes
and so cannot converge by construction. This is load-bearing rather than defensive:
in the recorded fixture set, *every* main question after the first arrives without
its label, so the repair fires on most main turns and is visible in the logs
(`Turn format repaired | repair=…`) as a generator-drift signal.

**An ungraded answer is a third state.** `score=None` used to mean both "the
candidate hasn't answered yet" and "the evaluator failed", which let a scorer
outage push the interview past its last question and silently drop the answer from
the average. `decide_next_turn` now takes `answered` alongside the score, and an
ungraded answer is persisted as `{"q": …, "unscored": True}` — excluded from the
overall, counted in `summary.unscored`, and stated in the closing message. A
partial result that says so beats a whole-looking one that isn't.

**Simpler-over-architectural choices:**
- `progression` is a pure function taking `max_followups` as an argument, not a
  stateful policy object.
- The turn-mode constants live in the domain (the FSM's home) and are re-exported
  by `prompts`, so the domain imports nothing outward.
- The ORM uses typed `Mapped` columns so a persisted field reads as its Python
  type across the app — typed boundaries without a mapping layer.

**Known debt (frozen behavior — not fixed here):**
- `prompts.prompt.get_system_prompt` is now used only by tests.
- **Prompt-injection hardening is deferred.** Job-description and CV text flow
  into the interviewer prompt as ordinary content, so a crafted job description
  can steer the interviewer's phrasing. The blast radius is already capped —
  progression is server-authoritative, the scorer is schema-constrained, and the
  closing turn is rendered rather than generated — so the worst case is an odd
  question, not a hijacked interview. Fixing it means adding a line to
  `prompts/interviewer.py` telling the model to treat that text as reference data
  and never as instructions, which is a deliberate prompt change: it alters the
  assembled bytes, so it needs its own commit, updated snapshots, and re-recorded
  cassettes (`make record`, requires API keys). Not something to slip in.
- **A follow-up answer is graded against the main question's key points.**
  `pipeline/interview` looks up the answered question's blueprint slot regardless
  of whether the turn answered was a follow-up, and follow-ups have no slot of
  their own. For a `simplify` follow-up this grades a deliberately easier question
  against the harder one's reference points, and `summary` then averages that
  record at full weight — so a candidate who stumbles once is penalised twice.
  Fixing it is a scoring-behavior change (drop the reference points for
  follow-ups, or weight them below main answers) and belongs in its own commit.
- **The interviewer, the scorer, and the judge can share one model.** With
  `generator_model` unset they all run on `settings.model`, so the judge is most
  likely to approve exactly the failures the generator is prone to, and the
  generator eval's kappa gate cannot see correlated error — only disagreement.
  Splitting generation out is now a config change; splitting the *judge* onto a
  stronger model than the thing it judges is not yet possible.

Resolved since the freeze (see git history): import-time DDL and the deprecated
`on_event` hook (now a lifespan), `datetime.utcnow` (now aware UTC on
`timestamptz` columns), wildcard CORS (now `settings.cors_origins`), and the
vendor-exception leak in `voice.py`.

## Running it in public

The API is unauthenticated by design and every endpoint spends money with a third
party per call, so two independent caps make publishing the URL safe
(`api/limits.py`, counters in `persistence/usage.py`):

- **Per-IP quotas** — sessions, turns, CV uploads, transcriptions, and TTS charged
  by character rather than by call, since synthesis is billed by length.
- **A daily instance-wide token ceiling** — the backstop that bounds the bill
  regardless of how requests are spread across addresses. It is the cruder cap
  and the one that actually guarantees a maximum.

Counters live in Postgres, not memory, so limits survive a restart and hold
across replicas. Windows are fixed rather than sliding: one upsert per check, and
the worst case (up to 2x the limit when straddling a boundary) is irrelevant at
the scale these defend against.

Client IP comes from `X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true`. That
must stay false unless a proxy is definitely in front and rewriting the header —
otherwise any caller resets their own limit by forging it.

Uploaded CVs are personal data. `DELETE /api/sessions/{id}` erases a session on
request, and `scripts/purge_expired.py` (scheduled, not in-process) sweeps
anything past `SESSION_RETENTION_DAYS`.

## Streaming

`POST /chat/stream` delivers a turn as server-sent events: `score` (the grade for
the previous answer, known before the next question exists), then `delta` per
chunk, then `done` carrying the same `ChatResponse` the buffered endpoint returns.

Streaming is modelled as a **delivery detail, not a second kind of request**. The
request dict handed to the waist is byte-identical to the buffered one — both are
built by `llm._generate_request` — so a streamed call hashes to the same cassette.
A recording made either way replays either way, and outputs cannot diverge by
transport. Under replay the recorded reply is re-chunked deterministically: the
pieces are arbitrary, the concatenation is not.

`run_turn` and `stream_turn` share `_decide_turn` and `_finish_turn`, so scoring,
progression, and prompt assembly are literally the same code; only delivery
differs. `tests/contract/test_streaming_identity.py` drives every scenario both
ways and asserts the resulting interviews are equal.

Provider streams are not retried — by the time one fails, part of the reply is
already delivered, so a retry would append rather than replace.
