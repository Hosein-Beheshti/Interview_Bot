# AI Interviewer

A full-stack AI mock-interview platform. Paste a job description (and optionally a CV), then run a voice or text interview with an adaptive interviewer that asks role-specific questions, probes shallow answers with follow-ups, and scores every response in real time.

> **Live demo:** _https://your-frontend.up.railway.app_ &nbsp;(update with your deployment URL)

---

## Features

- **Job-aware interviews** — paste a job description; the backend extracts a structured profile (role, seniority, key skills, focus areas) and tailors questions to what the role actually requires.
- **CV-aware questioning** — upload a CV (PDF) and questions are grounded in the candidate's real experience via semantic retrieval (RAG), without inventing details.
- **Adaptive follow-ups** — a server-side state machine decides each turn: a promising-but-shallow answer earns a deeper follow-up; an "I don't know" earns a supportive, simpler question on the same topic. Follow-ups never consume a main-question slot.
- **Honest scoring** — every answer is scored 1–10 across weighted rubric dimensions with concrete strengths and improvements. A non-answer scores 0.
- **Voice or text** — speak answers and hear questions read aloud (Deepgram STT/TTS), or type. Voice and text are interchangeable mid-interview.
- **Server-computed summary** — overall score, per-answer breakdown, key takeaways, and a copy-to-clipboard export, all computed on the backend.
- **Session persistence** — interviews survive a refresh and can be resumed.

## How It Works

The interviewer is **not** trusted to count questions or decide when to stop — that logic is server-authoritative:

1. Each candidate answer is scored in a dedicated, schema-constrained tool-use call that also classifies the answer (`substantive` / `partial` / `no_answer`) and flags whether a follow-up is warranted.
2. A pure state machine consumes those signals and picks the next turn — `main_question`, `follow_up` (deepen or simplify), or `closing` — enforcing the question budget and a per-question follow-up cap.
3. The chosen turn is rendered into a precise instruction for the model, so progression can never drift.

This keeps the LLM responsible for *language* and the server responsible for *control* — the result is predictable interview length, correct numbering, and graceful handling of edge cases like non-answers.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI, Python, SQLAlchemy |
| AI | Claude (Anthropic) — interviewing & scoring via strict tool use |
| Embeddings / RAG | Voyage AI embeddings, pgvector |
| Voice | Deepgram (STT + TTS), Web Speech API |
| Database | PostgreSQL + pgvector |
| Deployment | Docker, Railway |

## Project Structure

```
backend/
  routes/        FastAPI endpoints (chat, sessions, cv, voice, health)
  services/
    llm.py          Claude calls (chat, scoring, profile extraction)
    progression.py  Server-authoritative interview state machine
    prompt.py       Mode-aware system prompts
    rubric.py       Data-driven scoring rubric + tool schema
    evaluation.py   Validates & parses model scores
    summary.py      Server-side result aggregation
    job_profile.py  Structured job-profile extraction
    rag.py / embeddings.py / vector_store.py / cv_parser.py   CV ingestion & retrieval
    stt.py / tts.py Deepgram voice
  models/        SQLAlchemy models & Pydantic schemas
  tests/         Pytest suite
frontend/
  src/           React app (chat UI, voice, CV upload)
```

## Getting Started

### Prerequisites
- Docker and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/) (required)
- A [Deepgram API key](https://deepgram.com/) (voice) and [Voyage API key](https://www.voyageai.com/) (CV/RAG) — optional but recommended

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
| `ANTHROPIC_API_KEY` | Yes | — | Powers the interviewer and scoring |
| `DEEPGRAM_API_KEY` | For voice | — | Speech-to-text and text-to-speech |
| `VOYAGE_API_KEY` | For CV | — | Embeddings for CV retrieval |
| `DATABASE_URL` | No | `postgresql://postgres:postgres@db:5432/interview_bot` | Postgres + pgvector connection |
| `MODEL` | No | `claude-haiku-4-5-20251001` | Claude model id |
| `MAX_QUESTIONS` | No | `5` | Main questions per interview |
| `MAX_FOLLOWUPS_PER_QUESTION` | No | `1` | Follow-up turns allowed per question |

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

The suite covers scoring/parsing, the progression state machine, prompt rendering, summary aggregation, and job-profile extraction.

## Deployment

Deployed on Railway as three services — PostgreSQL (pgvector), backend, and frontend. See [QUICKSTART.md](QUICKSTART.md) for full deployment steps.
