"""Chat endpoints — a thin shell over the interview engine.

HTTP concerns only: resolve/create the session (404 vs. create-new policy), run
one interview turn, commit, and map the domain result to the API response.

Two shapes of the same turn. `POST /chat` answers once the turn is complete;
`POST /chat/stream` sends the same result as server-sent events, so the score for
the previous answer appears immediately and the next question arrives as it is
written. Both run identical engine code and persist identical state.
"""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from interview_bot import llm
from interview_bot.api import limits
from interview_bot.api.auth import get_current_user, require_owner
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
from interview_bot.persistence.database import SessionLocal, get_db
from interview_bot.persistence.models import User
from interview_bot.pipeline import interview
from interview_bot.pipeline import session as session_flow
from interview_bot.pipeline.interview import InterviewError
from interview_bot.prompts import scoring as scorer_prompt
from interview_bot.telemetry import accumulate_token_usage, observe_turn

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[
        Depends(limits.enforce(limits.INTERVIEW_TURN)),
        Depends(limits.require_token_budget),
    ],
)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    session = await _resolve_session(request, db, user.id)
    logger.info(f"Chat | session={session.session_id} | status={session.status}")

    if session.status == "complete":
        raise HTTPException(status_code=400, detail="Interview already completed")

    profile = session_store.resolve_profile(session)
    # Meter what the turn actually spends across all of its provider calls, so the
    # instance-wide ceiling reflects real usage rather than an estimate. A turn
    # that fails halfway still spent tokens, hence the `finally`.
    tokens: dict[str, int] = {}
    try:
        with accumulate_token_usage() as tokens:
            async with observe_turn(
                "interview_turn",
                session_id=session.session_id,
                input={"message": request.message},
                metadata={
                    "role": session.role,
                    "has_cv": session.has_cv,
                    "status": session.status,
                },
            ):
                result = await interview.run_turn(session, request.message, profile)
    except InterviewError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        limits.record_tokens(tokens)

    db.add(session)
    _record_score(db, session.session_id, result)
    db.commit()
    db.refresh(session)

    return _to_chat_response(session, result)


@router.post(
    "/chat/stream",
    dependencies=[
        Depends(limits.enforce(limits.INTERVIEW_TURN)),
        Depends(limits.require_token_budget),
    ],
)
async def chat_stream(
    request: ChatRequest, user: User = Depends(get_current_user)
) -> StreamingResponse:
    """The same turn as `/chat`, delivered as server-sent events.

    Event sequence: `score` (the grade for the previous answer, available before
    the next question exists), then `delta` per text chunk, then `done` carrying
    the identical ChatResponse `/chat` would have returned. `error` replaces the
    remainder if the turn fails.

    Errors after the first byte cannot become an HTTP status — the response has
    already begun — so they are delivered as an `error` event instead, and the
    client must treat a stream that ends without `done` as a failure.
    """
    return StreamingResponse(
        _turn_events(request, user.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells nginx not to buffer the response into a single write, which
            # would defeat the point of streaming it.
            "X-Accel-Buffering": "no",
        },
    )


async def _turn_events(request: ChatRequest, user_id: str) -> AsyncIterator[str]:
    """Run one streamed turn, owning its own database session.

    The session is opened here rather than injected: a `Depends(get_db)` session
    is closed when the response object is returned, which for a streaming
    response is before any of this body has run. The row lock taken on the
    interview must also be held until the turn is committed.
    """
    tokens: dict[str, int] = {}
    with SessionLocal() as db:
        try:
            session = await _resolve_session(request, db, user_id)
            if session.status == "complete":
                yield _event("error", {"detail": "Interview already completed"})
                return

            logger.info(f"Chat stream | session={session.session_id} | status={session.status}")
            profile = session_store.resolve_profile(session)

            with accumulate_token_usage() as tokens:
                async with observe_turn(
                    "interview_turn",
                    session_id=session.session_id,
                    input={"message": request.message},
                    metadata={
                        "role": session.role,
                        "has_cv": session.has_cv,
                        "status": session.status,
                        "streamed": True,
                    },
                ):
                    async for kind, payload in interview.stream_turn(
                        session, request.message, profile
                    ):
                        if kind == "score":
                            yield _event(
                                "score",
                                {"score": _to_score_result(payload).model_dump()}
                                if payload
                                else {"score": None},
                            )
                        elif kind == "delta":
                            yield _event("delta", {"text": payload})
                        else:
                            db.add(session)
                            _record_score(db, session.session_id, payload)
                            db.commit()
                            db.refresh(session)
                            yield _event(
                                "done", _to_chat_response(session, payload).model_dump()
                            )
        except HTTPException as e:
            yield _event("error", {"detail": e.detail})
        except InterviewError as e:
            yield _event("error", {"detail": str(e)})
        except Exception as e:
            logger.error(f"Chat stream failed | error={e}")
            yield _event("error", {"detail": "AI service unavailable"})
        finally:
            limits.record_tokens(tokens)


def _event(name: str, data: dict) -> str:
    """One server-sent event frame."""
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _record_score(db: Session, session_id: str, result: interview.TurnResult) -> None:
    """Stage the turn's full evaluator judgement, if it produced one.

    Written here rather than in the engine because the engine deliberately owns
    no transaction: the route is what decides a turn survived, and the judgement
    must land in that same commit or not at all.
    """
    if result.score_data is None:
        return
    session_store.record_answer_score(
        db,
        session_id=session_id,
        question_number=result.answered_question,
        follow_up=result.answered_follow_up,
        score=result.score_data,
        prompt_version=scorer_prompt.PROMPT_VERSION,
        rubric_version=rubric.RUBRIC_VERSION,
        model=llm.active_model(),
    )


def _to_chat_response(session, result: interview.TurnResult) -> ChatResponse:
    """Map an engine result plus the persisted session to the wire response."""
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


async def _resolve_session(request: ChatRequest, db: Session, user_id: str):
    """Existing session (locked, 404 if missing, 403 if not the caller's) or a
    lazily-created one, owned by `user_id` and debited for its credit cost."""
    if request.session_id:
        session = session_store.get(db, request.session_id, lock=True)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        require_owner(session, user_id)
        return session
    try:
        return await session_flow.create_from_context(
            db,
            job_context=request.job_context,
            role=request.role,
            num_questions=request.num_questions or settings.max_questions,
            user_id=user_id,
        )
    except session_flow.InsufficientCreditsError as e:
        raise HTTPException(status_code=402, detail="Insufficient credits.") from e


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
