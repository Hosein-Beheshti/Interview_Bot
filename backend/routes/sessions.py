"""Interview session creation from free-text job context."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.schemas import JobProfileSchema, SessionCreateRequest, SessionCreateResponse
from services import session as session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
async def create_session(
    request: SessionCreateRequest, db: Session = Depends(get_db)
) -> SessionCreateResponse:
    profile = await session_service.build_profile(request.job_context)
    session = session_service.create(
        db,
        profile=profile,
        num_questions=request.num_questions,
        job_context=request.job_context,
    )
    return SessionCreateResponse(
        session_id=session.session_id,
        role=profile.role,
        num_questions=session.num_questions,
        job_profile=JobProfileSchema(**profile.to_dict()),
    )
