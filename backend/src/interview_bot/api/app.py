from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from interview_bot.api.routes.chat import router as chat_router
from interview_bot.api.routes.cv import router as cv_router
from interview_bot.api.routes.health import router as health_router
from interview_bot.api.routes.sessions import router as sessions_router
from interview_bot.api.routes.voice import router as voice_router
from interview_bot.persistence.database import engine
from interview_bot.persistence.migrations import run_migrations
from interview_bot.persistence.models import Base
from interview_bot.persistence.vector_store import ensure_extension
from interview_bot.telemetry import shutdown as observability_shutdown

ensure_extension()
Base.metadata.create_all(bind=engine)
run_migrations()

app = FastAPI(title="Interview Bot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(cv_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")


@app.on_event("shutdown")
def _flush_observability() -> None:
    """Flush buffered traces so the last events aren't lost on shutdown."""
    observability_shutdown()
