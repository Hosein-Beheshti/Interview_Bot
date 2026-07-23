"""Interview session creation from free-text job context."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from interview_bot.api.schemas import (
    JobProfileSchema,
    PlanSlotSchema,
    SessionCreateRequest,
    SessionCreateResponse,
)
from interview_bot.persistence.database import get_db
from interview_bot.pipeline import session as session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
async def create_session(
    request: SessionCreateRequest, db: Session = Depends(get_db)
) -> SessionCreateResponse:
    profile = await session_service.build_profile(request.job_context)
    interview_plan = await session_service.build_plan(profile, request.num_questions)
    session = session_service.create(
        db,
        profile=profile,
        num_questions=request.num_questions,
        job_context=request.job_context,
        interview_plan=interview_plan,
    )
    plan_slots = (
        [PlanSlotSchema(**slot.to_dict()) for slot in interview_plan.slots]
        if interview_plan
        else []
    )
    return SessionCreateResponse(
        session_id=session.session_id,
        role=profile.role,
        num_questions=session.num_questions,
        job_profile=JobProfileSchema(**profile.to_dict()),
        plan=plan_slots,
    )
