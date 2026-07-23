# AI Interviewer

A full-stack AI mock-interview platform. Paste a job description (and optionally a CV), then run a voice or text interview with an adaptive interviewer that asks role-specific questions, probes shallow answers with follow-ups, and scores every response in real time.

> **Live demo:** _https://your-frontend.up.railway.app_ &nbsp;(update with your deployment URL)

---

## Features

- **Job-aware interviews** — paste a job description; the backend extracts a structured profile (role, seniority, key skills, focus areas) and tailors questions to what the role actually requires.
- **CV-aware questioning** — upload a CV (PDF) and questions are grounded in the candidate's real experience via semantic retrieval (RAG), without inventing details.
- **Adaptive follow-ups** — a server-side state machine decides each turn: a promising-but-shallow answer earns a deeper follow-up; an "I don't know" earns a supportive, simpler question on the same topic. Follow-ups never consume a main-question slot.
- **Calibrated scoring** — every answer is scored 1–10 across weighted rubric dimensions. The scorer writes a `critique` first (chain-of-thought before numbers) to anchor calibration and suppress leniency bias. The constant rubric is prompt-cached to minimise cost. A non-answer scores 0.
- **Swappable LLM backend** — interviewing and scoring run through a provider abstraction. Switch between Anthropic (Claude) and Google Gemini with a single env var; no application code changes.
- **Voice or text** — speak answers and hear questions read aloud (Deepgram STT/TTS), or type. Voice and text are interchangeable mid-interview.
- **Server-computed summary** — overall score, per-answer breakdown, key takeaways, and a copy-to-clipboard export, all computed on the backend.
- **Session persistence** — interviews survive a refresh and can be resumed.

## How It Works

The interviewer is **not** trusted to count questions or decide when to stop — that logic is server-authoritative:

1. Each candidate answer is scored in a dedicated, schema-constrained structured-output call. The scorer classifies the answer (`substantive` / `partial` / `no_answer`), writes a short `critique` first, then fills in per-dimension scores — forcing chain-of-thought before judgment.
2. A pure state machine consumes the score signals and picks the next turn — `main_question`, `follow_up` (deepen or simplify), or `closing` — enforcing the question budget and a per-question follow-up cap.
3. The chosen turn is rendered into a precise instruction for the model, so progression can never drift.

This keeps the LLM responsible for *language* and the server responsible for *control* — the result is predictable interview length, correct numbering, and graceful handling of edge cases like non-answers.

> **Want the full picture?** [ARCHITECTURE.md](ARCHITECTURE.md) is a detailed, course-style walkthrough of every file, the request flow, and the reasoning behind each design decision (the control-vs-language split, the scoring sub-call, the progression state machine, RAG, and where the LLM is — and deliberately isn't — agentic).

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI, Python, SQLAlchemy |
| AI | Claude (Anthropic) or Gemini (Google) — configurable via `LLM_PROVIDER` |
| Embeddings / RAG | Voyage AI embeddings, pgvector |
| Voice | Deepgram (STT + TTS), Web Speech API |
| Database | PostgreSQL + pgvector |
| Deployment | Docker, Railway |

## Project Structure

The backend is an installable package (`src/interview_bot/`) organized by a
**pure core, imperative shell** rule — dependencies point inward, and it's
enforced mechanically by import-linter, not by convention:

```
backend/src/interview_bot/
  domain/          PURE. no network, I/O, clock, or env — zero-mock testable
    progression.py   server-authoritative interview FSM (turn decisions)
    rubric.py        data-driven scoring rubric + weighted overall + RUBRIC_VERSION
    evaluation.py    ScoreData + parse/validate model scores (incl. critique)
    job_profile.py   structured job profile + prompt-ready context
    plan.py          interview blueprint (one slot per main question)
    summary.py       result aggregation
  prompts/         versioned prompt templates + pure render functions
    interviewer prompts, scoring prompt (+ PROMPT_VERSION), extraction prompts
  llm/             the transport waist + the one earned provider abstraction
    transport.py     record/replay seam (deterministic offline runs)
    provider.py      LLMProvider ABC; anthropic.py / gemini.py; registry.py
  integrations/    non-LLM vendor adapters (Voyage embeddings, Deepgram speech, CV parsing)
  retrieval/       RAG (chunk → embed → pgvector search)
  pipeline/        imperative shell: orchestration (run a turn) + session lifecycle
  api/             FastAPI app, routes, request/response DTOs
  persistence/     SQLAlchemy engine, ORM models, migrations, vector store, session CRUD
  telemetry/       structured tracing seam (tokens, cost, latency, versions)
  config.py        single validated settings object   logger.py   cli.py
backend/
  tests/unit + tests/contract   pure unit tests + cassette-backed offline tests
  fixtures/ (CVs, cassettes' recordings, scenarios)   cassettes/   scripts/
  evals/           first-class scorer eval: golden set, metrics, calibration
frontend/src/      React app (chat UI, voice, CV upload)
```

See **[docs/architecture.md](docs/architecture.md)** for the full module map, the
dependency rule, and the determinism story. (The older
[ARCHITECTURE.md](ARCHITECTURE.md) is a narrative deep-dive kept for background.)

## Getting Started

### Prerequisites
- Docker and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/) **or** a [Google AI Studio key](https://aistudio.google.com/apikey) (one is required)
- A [Deepgram API key](https://deepgram.com/) (voice) and [Voyage AI key](https://www.voyageai.com/) (CV/RAG) — optional but recommended

### Run locally

```bash
git clone https://github.com/Hosein-Beheshti/Interview_Bot.git
cd Interview_Bot

# Create backend/.env (see Configuration below)
cp backend/.env.example backend/.env   # then fill in your keys

docker-compose up --build
```

Then open **http://localhost:5173**. The API runs at **http://localhost:8000** (interactive docs at `/docs`).

**Backend only, without Docker:**

```bash
cd backend
make install     # editable install + dev tooling
make test        # offline fast tier — no keys, no network, no DB
make dev         # run the API (needs DATABASE_URL + a provider key)
```

## Configuration

Backend settings are read from `backend/.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | No | `anthropic` | `anthropic` or `gemini` |
| `ANTHROPIC_API_KEY` | If using Anthropic | — | Claude model access |
| `MODEL` | No | `claude-haiku-4-5-20251001` | Claude model id |
| `GEMINI_API_KEY` | If using Gemini | — | Gemini model access |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model id |
| `DEEPGRAM_API_KEY` | For voice | — | Speech-to-text and text-to-speech |
| `VOYAGE_API_KEY` | For CV | — | Embeddings for CV retrieval |
| `DATABASE_URL` | No | `postgresql://postgres:postgres@db:5432/interview_bot` | Postgres + pgvector connection |
| `MAX_QUESTIONS` | No | `5` | Main questions per interview |
| `MAX_FOLLOWUPS_PER_QUESTION` | No | `1` | Follow-up turns allowed per question |
| `GENERATION_TEMPERATURE` | No | `0.7` | Sampling temperature for interviewer replies |

## API Reference

All application routes are under `/api`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/sessions` | Create an interview from a job description |
| `POST` | `/api/chat` | Send a message; returns the next turn, score, and (on completion) summary |
| `POST` | `/api/cv/upload` | Upload and index a CV |
| `GET` | `/api/cv/{session_id}` | CV indexing status |
| `DELETE` | `/api/cv/{session_id}` | Remove an indexed CV |
| `POST` | `/api/transcribe` | Speech-to-text (Deepgram) |
| `POST` | `/api/speak` | Text-to-speech (Deepgram) |
| `GET` | `/health` | Health check |

## Determinism & measurement

A nondeterministic system (LLM calls) is made **reproducible and measurable** so
a refactor can't silently change behavior:

- **Record/replay seam.** Every model-provider call funnels through one transport
  waist (`llm/transport.py`). `record` mode captures each request/response/latency/
  token-count to a content-hashed cassette; `replay` serves them from disk with
  **no network and no API keys**. The request's canonical bytes are the cassette
  identity, so any prompt drift misses its cassette and fails loudly.
- **Behavior freeze.** Contract tests run the full pipeline under replay and assert
  byte-identical golden outputs, **exact assembled prompt bytes**, and FSM
  trajectories — all offline, in seconds. An unintended prompt change fails the
  snapshot loudly and requires an explicit update.
- **Versioned prompts & rubric.** `PROMPT_VERSION` and `RUBRIC_VERSION` are derived
  from their own content, so they change automatically when the prompt or rubric
  changes. Every scoring call emits both on its trace, so a score is always
  traceable to what produced it — results across versions are never silently compared.
- **Telemetry by default.** Every LLM call emits provider, model, tokens in/out,
  cost, latency, and prompt/rubric version.

## Testing

```bash
cd backend
make test        # offline fast tier: ruff + mypy + import-linter + pytest under replay
make test-fast   # just the tests (unit + contract), offline, no keys
```

`make test` needs no API keys, no network, and no database. The unit suite covers
scoring/parsing (incl. the critique field), the progression FSM, prompt rendering,
summary aggregation, job-profile extraction, and the eval metrics; the contract
suite freezes full-pipeline outputs, prompts, and trajectories under replay.

### Scorer evaluation (needs API keys)

```bash
cd backend
make eval                                   # full golden set through the live scorer
python -m evals.run_eval --limit 5          # cheap smoke test
python -m evals.run_eval --json-out report.json          # versioned results artifact
python -m evals.run_eval --calibrate 5 --json-out cal.json   # judge self-consistency + agreement
```

Quality gates: ≥70% in-band overall rate, ≥75% `answer_type` accuracy, 0 adversarial
hard-fails. The results artifact records model, prompt/rubric version, and per-item
cost/latency. See **[docs/evaluation.md](docs/evaluation.md)** for what's measured,
the calibration metrics, and known limits.

## Deployment

Deployed on Railway as three services — PostgreSQL (pgvector), backend, and frontend. See [QUICKSTART.md](QUICKSTART.md) for full deployment steps.
