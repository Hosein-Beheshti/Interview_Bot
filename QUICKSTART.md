# Interview Bot - Quick Start (5 minutes)

## Prerequisites

- Python 3.8+ (you have this)
- Node.js 18+ (download from nodejs.org if needed)
- Your Anthropic API key in `backend/.env`

## Run Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs at: **http://localhost:8000**

API docs: http://localhost:8000/docs

## Run Frontend (in new terminal)

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at: **http://localhost:5173**

## That's It

Open http://localhost:5173 in your browser — the chat interface is ready.

---

## Full Flow

1. **Backend terminal:** `cd backend && uvicorn main:app --reload`
2. **Frontend terminal:** `cd frontend && npm install && npm run dev`
3. **Browser:** Open http://localhost:5173
4. Click **Start Interview**
5. Answer all 5 questions
6. Get your score and feedback

---

## Or Use Docker Compose (one command)

```bash
docker-compose up --build
```

Then open http://localhost:5173

---

## Troubleshooting

**"npm not found"**
- Download Node.js from nodejs.org
- Then: `npm install` in the frontend directory

**Backend says "Interview not found"**
- Sessions are in-memory, so restart clears them
- This is Step 1 MVP (Step 2 adds database)

**CORS errors**
- Backend is already configured to allow localhost:5173
- Make sure both services are running

**Port already in use**
- Backend: Change port in `backend/config.py` or use `--port 8001`
- Frontend: Change port in `frontend/vite.config.ts`
