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

```
backend/
  routes/          FastAPI endpoints (chat, sessions, cv, voice, health)
  services/
    session.py     Session lifecycle: creation, lookup, profile resolution
    interview/     The interview domain (pure-ish business logic)
      orchestration.py  Runs one turn: score → decide → generate
      progression.py    Server-authoritative interview state machine
      prompt.py         Mode-aware system prompts
      rubric.py         Data-driven scoring rubric + structured-output schema
      evaluation.py     Validates & parses model scores (incl. critique field)
      job_profile.py    Structured job-profile extraction
      summary.py        Server-side result aggregation
    integrations/  Vendor adapters (the only code that knows the vendors)
      llm.py            Provider-agnostic LLM facade (generate, generate_structured, parse)
      providers/        Anthropic and Gemini backends
      embeddings.py     Voyage embeddings
      speech.py         Deepgram STT + TTS
      rag.py / vector_store.py / cv_parser.py   CV ingestion & retrieval
  models/          SQLAlchemy models & Pydantic schemas
  tests/           Pytest unit suite
  evals/           Offline scorer evaluation harness
    golden_set.json  Human-reviewed test cases (24 items, tagged by difficulty)
    run_eval.py      CI-runnable harness with in-band, accuracy, and adversarial gates
frontend/
  src/             React app (chat UI, voice, CV upload)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for a file-by-file explanation of how these fit together.

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

## Testing

```bash
cd backend
pytest
```

The unit suite covers scoring/parsing (incl. critique field), the progression state machine, prompt rendering, summary aggregation, and job-profile extraction.

### Scorer evaluation

An offline eval harness measures scoring calibration against a human-reviewed golden set:

```bash
cd backend
python -m evals.run_eval                   # full 24-item golden set
python -m evals.run_eval --limit 5         # smoke test (cheap)
python -m evals.run_eval --json-out report.json
```

Quality gates: ≥70% in-band overall rate, ≥75% `answer_type` classification accuracy, 0 adversarial hard-fails. The golden set covers strong/good/partial/no-answer tiers, confidently-wrong answers, prompt-injection attempts, and dimension-divergence edge cases.

## Deployment

Deployed on Railway as three services — PostgreSQL (pgvector), backend, and frontend. See [QUICKSTART.md](QUICKSTART.md) for full deployment steps.
