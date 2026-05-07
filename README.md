# Interview Bot

AI-powered technical interview practice with structured scoring, voice support, and persistent sessions.

**Stack:** FastAPI · Claude (Anthropic) · React + TypeScript · PostgreSQL · Docker

---

## Features

- 5-question structured technical interviews
- Real-time chat interface
- Structured JSON scoring (1-10 + strengths + improvements)
- Voice input (speech-to-text) and output (text-to-speech)
- Session persistence (PostgreSQL)
- Resume interrupted interviews via localStorage
- Multiple role types (Software Engineer, DevOps, Frontend, etc.)

## Architecture

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Browser    │─────▶│   FastAPI    │─────▶│  Anthropic   │
│   (React)    │◀─────│   Backend    │◀─────│   Claude     │
└──────┬───────┘      └──────┬───────┘      └──────────────┘
       │                     │
       │              ┌──────▼───────┐
       │              │  PostgreSQL  │
       │              │   Database   │
       └─ localStorage└──────────────┘
```

**Backend layers:**
- `routes/` — HTTP endpoints (thin)
- `services/` — Business logic (LLM calls, prompts, score parsing)
- `models/` — Pydantic schemas + SQLAlchemy ORM

**Frontend layers:**
- `components/` — React UI
- `hooks/` — State + side effects (chat, voice)
- `services/` — API client
- `types/` — TypeScript interfaces

---

## Project Structure

```
interview-bot/
├── backend/
│   ├── main.py              # FastAPI app + middleware
│   ├── config.py            # Settings via pydantic-settings
│   ├── database.py          # SQLAlchemy engine + session
│   ├── logger.py            # Structured logging
│   ├── routes/              # HTTP endpoints
│   ├── services/            # Business logic
│   ├── models/              # Schemas + ORM
│   ├── tests/               # pytest tests
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/      # ChatInterface
│   │   ├── hooks/           # useChat, useVoice
│   │   ├── services/        # API client
│   │   ├── types/           # TS interfaces
│   │   └── styles/
│   └── package.json
│
├── docker-compose.yml       # backend + frontend + db
├── .env.example
└── README.md
```

## Quick Start

### Prerequisites
- Docker Desktop
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

### Run

```bash
# 1. Add your API key
cp .env.example backend/.env
# Edit backend/.env: ANTHROPIC_API_KEY=sk-ant-...

# 2. Launch everything
docker-compose up --build
```

Open **http://localhost:5173**

### Without Docker

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## API

### `POST /api/chat`

Start or continue an interview.

**Request:**
```json
{
  "message": "Hi, ready to start",
  "session_id": "uuid-or-null",
  "role": "Software Engineer"
}
```

**Response:**
```json
{
  "reply": "Question 1: ...",
  "session_id": "uuid",
  "question_number": 1,
  "is_complete": false,
  "score": {
    "score": 8,
    "strengths": ["..."],
    "improvements": ["..."]
  }
}
```

### `GET /health`
Health check.

---

## Database Schema

**`interview_sessions`**

| Column | Type | Notes |
|---|---|---|
| `session_id` | VARCHAR | Primary key (UUID) |
| `role` | VARCHAR | Job role |
| `messages` | JSON | Full conversation |
| `answers_given` | INTEGER | Progress (0-5) |
| `is_complete` | BOOLEAN | |
| `created_at` | TIMESTAMP | |

---

## Testing

```bash
cd backend
pytest tests/
```

---

## Design Decisions & Tradeoffs

This is a portfolio project. Some decisions were made for clarity over production-grade hardening — and I want to be explicit about them.

**Voice (Web Speech API):**
- Free and works in-browser, but accuracy on technical terms is mediocre
- Production choice: **Whisper** for STT, **ElevenLabs/OpenAI TTS** for output

**Score parsing (regex on Claude's output):**
- Works but fragile if Claude formats unexpectedly
- Production choice: **Anthropic's structured outputs** beta or strict tool use

**Sessions stored as JSON in Postgres:**
- Simple and queryable, but not optimized for high volume
- Production choice: separate `messages` table with foreign key

**No authentication:**
- Sessions are opaque UUIDs; anyone with the ID can access them
- Production: JWT or session cookies

**Schema migrations:**
- Currently uses `Base.metadata.create_all()` (dev-only)
- Production: Alembic for proper migrations

---

## Roadmap

- [x] Step 1: FastAPI MVP + React frontend
- [x] Step 2: PostgreSQL persistence + resume via localStorage
- [x] Step 3: Structured JSON scoring
- [x] Step 4: Voice input/output (Web Speech API)
- [ ] Step 5: User accounts + interview history dashboard
- [ ] Step 6: Whisper + ElevenLabs (production-grade voice)
- [ ] Step 7: Deploy to production (Vercel + Railway/Render)

---

## License

MIT
