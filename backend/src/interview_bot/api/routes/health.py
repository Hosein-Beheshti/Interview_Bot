"""Liveness and readiness probes.

Deliberately two endpoints. `/health` answers "is this process alive?" and must
never touch a dependency — otherwise a database blip makes the platform kill and
restart containers that were working fine, turning a brief outage into a crash
loop. `/health/ready` answers "can this process serve traffic?" and is what a
load balancer should gate on.
"""
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from interview_bot.logger import logger
from interview_bot.persistence.database import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up and serving. No dependency checks by design."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(response: Response) -> dict[str, str]:
    """Readiness: the database is reachable, so a request can actually be served."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning(f"Readiness check failed | error={e}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ready"}
