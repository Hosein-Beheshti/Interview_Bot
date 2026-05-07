# AI Interviewer

A full-stack AI-powered mock interview app with voice interaction, real-time scoring, and role-specific technical questions.

Live demo: https://your-frontend.up.railway.app

## Features

- Role-specific questions — type any role (Software Engineer, DevOps, ML Engineer, etc.) and get tailored technical questions
- Voice interaction — speak your answers via microphone, hear questions read aloud via Deepgram TTS
- Real-time scoring — each answer is scored 1–10 with strengths and improvement areas
- Interview summary — overall score, per-question breakdown, and key takeaways at the end
- Copy results — export your full interview results to clipboard
- Session persistence — resume an interrupted interview

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI, Python |
| AI | Claude (Anthropic) |
| Voice | Deepgram TTS, Web Speech API |
| Database | PostgreSQL |
| Deployment | Railway, Docker |

## Local Setup

### Prerequisites
- Docker and Docker Compose
- Anthropic API key
- Deepgram API key

### Steps

1. Clone the repo
   ```bash
   git clone https://github.com/Hosein-Beheshti/Interview_Bot.git
   cd Interview_Bot
   ```

2. Create `backend/.env`
   ```
   ANTHROPIC_API_KEY=your_anthropic_key
   DEEPGRAM_API_KEY=your_deepgram_key
   ```

3. Start the app
   ```bash
   docker-compose up --build
   ```

4. Open http://localhost:5173

## Deployment

Deployed on Railway with three services: PostgreSQL, backend, and frontend. See [QUICKSTART.md](QUICKSTART.md) for full deployment steps.
