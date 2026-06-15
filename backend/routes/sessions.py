"""Interview session creation from free-text job context."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from logger import logger
from models.interview import InterviewSession
from models.schemas import JobProfileSchema, SessionCreateRequest, SessionCreateResponse
from services import job_profile as job_profile_service
from services import llm

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
async def create_session(
    request: SessionCreateRequest, db: Session = Depends(get_db)
) -> SessionCreateResponse:
    profile = await build_profile(request.job_context)

    session = InterviewSession(
        session_id=str(uuid.uuid4()),
        role=profile.role,
        num_questions=request.num_questions,
        messages=[],
        job_context=request.job_context,
        job_profile=profile.to_dict(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(
        f"Session created | id={session.session_id} | role={profile.role} | "
        f"skills={len(profile.key_skills)} | questions={request.num_questions}"
    )
    return SessionCreateResponse(
        session_id=session.session_id,
        role=profile.role,
        num_questions=session.num_questions,
        job_profile=JobProfileSchema(**profile.to_dict()),
    )


async def build_profile(job_context: str) -> job_profile_service.JobProfile:
    """Extract a structured profile, degrading to a role-only profile on failure."""
    try:
        raw = await llm.extract_job_profile(job_context)
        return job_profile_service.parse_profile(
            raw, fallback_role=settings.default_role
        )
    except Exception as e:
        logger.warning(
            f"Job profile extraction failed, using fallback | "
            f"error_type={type(e).__name__} | error={e}"
        )
        return job_profile_service.minimal(settings.default_role)
