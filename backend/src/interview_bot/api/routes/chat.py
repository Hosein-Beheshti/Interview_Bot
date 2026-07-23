"""Chat endpoint — a thin shell over the interview engine.

HTTP concerns only: resolve/create the session (404 vs. create-new policy), run
one interview turn, commit, and map the domain result to the API response.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from interview_bot.api.schemas import (
    ChatRequest,
    ChatResponse,
    DimensionScore,
    InterviewSummary,
    ScoreResult,
)
from interview_bot.config import settings
from interview_bot.domain import rubric
from interview_bot.domain.scoring import ScoreData
from interview_bot.logger import logger
from interview_bot.persistence import sessions as session_store
from interview_bot.persistence.database import get_db
from interview_bot.pipeline import interview
from interview_bot.pipeline import session as session_flow
from interview_bot.pipeline.interview import InterviewError
from interview_bot.telemetry import observe_turn

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    session = await _resolve_session(request, db)
    logger.info(f"Chat | session={session.session_id} | status={session.status}")

    if session.status == "complete":
        raise HTTPException(status_code=400, detail="Interview already completed")

    profile = session_store.resolve_profile(session)
    try:
        async with observe_turn(
            "interview_turn",
            session_id=session.session_id,
            input={"message": request.message},
            metadata={"role": session.role, "has_cv": session.has_cv, "status": session.status},
        ):
            result = await interview.run_turn(session, request.message, profile)
    except InterviewError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    db.add(session)
    db.commit()
    db.refresh(session)

    return ChatResponse(
        reply=result.reply,
        session_id=session.session_id,
        status=session.status,
        question_number=session.question_number,
        num_questions=session.num_questions,
        is_complete=session.is_complete,
        score=_to_score_result(result.score_data) if result.score_data else None,
        mode=result.mode,
        summary=InterviewSummary(**result.summary) if result.summary else None,
    )


async def _resolve_session(request: ChatRequest, db: Session):
    """Existing session (locked, 404 if missing) or a lazily-created one."""
    if request.session_id:
        session = session_store.get(db, request.session_id, lock=True)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    return await session_flow.create_from_context(
        db,
        job_context=request.job_context,
        role=request.role,
        num_questions=request.num_questions or settings.max_questions,
    )


def _to_score_result(score_data: ScoreData) -> ScoreResult:
    """Map the domain score to the API DTO."""
    return ScoreResult(
        score=score_data.overall,
        dimensions=[
            DimensionScore(key=key, label=label, score=value)
            for key, label, value in rubric.labelled(score_data.dimensions)
        ],
        strengths=score_data.strengths,
        improvements=score_data.improvements,
    )
