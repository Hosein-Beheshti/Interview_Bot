"""Interview session creation from free-text job context."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from interview_bot.api.schemas import (
    JobProfileSchema,
    PlanSlotSchema,
    SessionCreateRequest,
    SessionCreateResponse,
)
from interview_bot.persistence import sessions as session_store
from interview_bot.persistence.database import get_db
from interview_bot.pipeline.plan import build_plan
from interview_bot.pipeline.profile import build_profile

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
async def create_session(
    request: SessionCreateRequest, db: Session = Depends(get_db)
) -> SessionCreateResponse:
    profile = await build_profile(request.job_context)
    interview_plan = await build_plan(profile, request.num_questions)
    session = session_store.create(
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


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db: Session = Depends(get_db)) -> Response:
    """Erase a session, its transcript, and its indexed CV.

    The candidate-facing "delete my data" action. Sessions also expire on their
    own (see `settings.session_retention_days`), but a person who uploaded a CV
    should not have to wait for that.
    """
    if not session_store.delete(db, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)
