"""Chat endpoint — a thin shell over the interview engine.

HTTP concerns only: resolve/create the session (404 vs. create-new policy), run
one interview turn, commit, and map the domain result to the API response.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from logger import logger
from models.schemas import ChatRequest, ChatResponse, DimensionScore, InterviewSummary, ScoreResult
from services import session as session_service
from services.interview import orchestration, rubric
from services.interview.evaluation import ScoreData
from services.interview.orchestration import InterviewError

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    session = await _resolve_session(request, db)
    logger.info(f"Chat | session={session.session_id} | status={session.status}")

    if session.status == "complete":
        raise HTTPException(status_code=400, detail="Interview already completed")

    profile = session_service.resolve_profile(session)
    try:
        result = await orchestration.run_turn(session, request.message, profile)
    except InterviewError as e:
        raise HTTPException(status_code=502, detail=str(e))

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
        session = session_service.get(db, request.session_id, lock=True)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    return await session_service.create_from_context(
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
