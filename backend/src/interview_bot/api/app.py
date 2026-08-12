"""FastAPI application wiring: lifespan, middleware, routers."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from interview_bot.api.routes.auth import router as auth_router
from interview_bot.api.routes.chat import router as chat_router
from interview_bot.api.routes.cv import router as cv_router
from interview_bot.api.routes.health import router as health_router
from interview_bot.api.routes.sessions import router as sessions_router
from interview_bot.api.routes.voice import router as voice_router
from interview_bot.config import is_dev_cors_in_production, settings
from interview_bot.integrations import speech
from interview_bot.logger import logger
from interview_bot.persistence import schema
from interview_bot.telemetry import shutdown as observability_shutdown


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the process lifecycle: prepare the schema, flush traces on the way out.

    Schema preparation belongs here rather than at import time. Importing this
    module must stay side-effect-free so tests and tooling do not need a
    reachable database, and so a slow or briefly unavailable database cannot
    stop the process from starting and answering its liveness probe.
    """
    if is_dev_cors_in_production(settings):
        logger.critical(
            f"CORS_ORIGINS is still the localhost default or a wildcard while "
            f"RAILWAY_ENVIRONMENT={settings.railway_environment!r} — set "
            f"CORS_ORIGINS to the real frontend origin."
        )
    schema.initialize()
    try:
        yield
    finally:
        await speech.close()
        observability_shutdown()


app = FastAPI(title="Interview Bot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(cv_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Sanitize anything that escapes a route's own try/except.

    FastAPI/Starlette dispatch by the most specific matching handler in the
    exception's MRO, so this never intercepts `HTTPException` — routes that
    raise it deliberately keep their real status code and detail untouched.
    """
    logger.error(f"Unhandled exception | path={request.url.path} | error={exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
