"""Interview session creation from free-text job context."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from interview_bot.api import credits, limits
from interview_bot.api.auth import get_current_user
from interview_bot.api.schemas import (
    JobProfileSchema,
    PlanSlotSchema,
    SessionCreateRequest,
    SessionCreateResponse,
)
from interview_bot.config import settings
from interview_bot.persistence import sessions as session_store
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import User
from interview_bot.pipeline.plan import build_plan
from interview_bot.pipeline.profile import build_profile
from interview_bot.telemetry import accumulate_token_usage

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=SessionCreateResponse,
    dependencies=[
        Depends(limits.enforce(limits.SESSION_CREATION)),
        Depends(limits.require_token_budget),
        Depends(credits.require(settings.interview_session_credit_cost)),
    ],
)
async def create_session(
    request: SessionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionCreateResponse:
    # Setup spends tokens too (profile extraction, then plan generation), so it
    # counts against the same instance-wide ceiling as an interview turn.
    tokens: dict[str, int] = {}
    try:
        with accumulate_token_usage() as tokens:
            profile = await build_profile(request.job_context)
            interview_plan = await build_plan(profile, request.num_questions)
    finally:
        limits.record_tokens(tokens)

    session = session_store.create(
        db,
        profile=profile,
        num_questions=request.num_questions,
        job_context=request.job_context,
        interview_plan=interview_plan,
        user_id=user.id,
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
async def delete_session(
    session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    """Erase a session, its transcript, and its indexed CV.

    The candidate-facing "delete my data" action. Sessions also expire on their
    own (see `settings.session_retention_days`), but a person who uploaded a CV
    should not have to wait for that.
    """
    session = session_store.get(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id is not None and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your session")
    session_store.delete(db, session_id)
    return Response(status_code=204)
