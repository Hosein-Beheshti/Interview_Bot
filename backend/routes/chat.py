import uuid
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from config import settings
from models.schemas import (
    ChatRequest,
    ChatResponse,
    DimensionScore,
    InterviewSummary,
    ScoreResult,
)
from models.interview import InterviewSession
from services import llm, prompt, evaluation, progression, rag, rubric
from services import summary as summary_service
from services.evaluation import ScoreData
from routes.sessions import build_profile
from database import get_db
from logger import logger

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    session = await _get_or_create_session(request, db)
    logger.info(
        f"Chat request | session={session.session_id} | "
        f"status={session.status} | answers={session.answers_given}"
    )

    if session.status == "complete":
        logger.warning(f"Attempt to use completed session: {session.session_id}")
        raise HTTPException(status_code=400, detail="Interview already completed")

    is_first_message = len(session.messages) == 0
    profile = session.resolve_profile()

    session.messages.append({"role": "user", "content": request.message})
    flag_modified(session, "messages")

    # Score the candidate's answer first (when there is one). Scoring yields the
    # control signals — answer_type and follow_up_recommended — that the server
    # uses to choose the next turn. The first message has no answer to score.
    # Capture which question is being answered BEFORE progression mutates state.
    score_data = None
    answered_q = answered_follow_up = None
    if not is_first_message:
        session.answers_given += 1
        answered_q = session.questions_asked
        answered_follow_up = session.followups_on_current > 0
        score_data = await _score_last_answer(session, profile)

    # Server-authoritative progression: decide what the next turn must be, then
    # tell the model exactly that. The model never owns the counter.
    mode, follow_up_kind = progression.decide_next_turn(session, score_data)

    try:
        cv_context = await _build_cv_context(session)
        system = prompt.get_system_prompt(
            profile,
            num_questions=session.num_questions,
            cv_context=cv_context,
            mode=mode,
            question_number=session.questions_asked + 1,
            follow_up_kind=follow_up_kind,
        )
        reply = await llm.chat(session.messages, system)
    except Exception as e:
        logger.error(f"LLM call failed | session={session.session_id} | error={e}")
        # Roll back the answer bookkeeping so a retry re-scores cleanly.
        if not is_first_message:
            session.answers_given -= 1
        raise HTTPException(status_code=502, detail="AI service unavailable")

    session.messages.append({"role": "assistant", "content": reply})
    flag_modified(session, "messages")

    if session.status == "created":
        session.status = "active"

    progression.apply_turn(session, mode)

    # Persist the score only now that the whole turn has succeeded, so a failed
    # generation followed by a retry cannot double-record an answer.
    if score_data is not None:
        session.scores = session.scores + [
            {
                "q": answered_q,
                "follow_up": answered_follow_up,
                "score": score_data.overall,
                "strengths": score_data.strengths,
                "improvements": score_data.improvements,
            }
        ]
        flag_modified(session, "scores")

    summary = None
    if session.is_complete:
        summary = summary_service.build_summary(profile.role, session.scores)

    db.add(session)
    db.commit()
    db.refresh(session)

    return ChatResponse(
        reply=reply,
        session_id=session.session_id,
        status=session.status,
        question_number=session.question_number,
        num_questions=session.num_questions,
        is_complete=session.is_complete,
        score=_to_score_result(score_data) if score_data else None,
        mode=mode,
        summary=InterviewSummary(**summary) if summary else None,
    )


async def _score_last_answer(session, profile) -> ScoreData | None:
    """Score the most recent answer against the rubric. Never raises.

    Called after the candidate's message is appended but before the interviewer's
    reply is generated, so the answer is the last message and the question is the
    most recent assistant message before it.
    """
    user_answer = session.messages[-1]["content"]
    last_question = next(
        (m["content"] for m in reversed(session.messages[:-1]) if m["role"] == "assistant"),
        "",
    )
    try:
        tool_input = await llm.score(last_question, user_answer, profile)
        score_data = evaluation.parse_score(tool_input)
        if not score_data:
            return None
        logger.info(
            f"Score | session={session.session_id} | "
            f"q={session.answers_given} | overall={score_data.overall} | "
            f"answer_type={score_data.answer_type} | "
            f"follow_up={score_data.follow_up_recommended}"
        )
        return score_data
    except Exception as e:
        logger.warning(
            f"Scoring failed | session={session.session_id} | "
            f"q={session.answers_given} | error_type={type(e).__name__} | error={e}"
        )
        return None


def _to_score_result(score_data: ScoreData) -> ScoreResult:
    return ScoreResult(
        score=score_data.overall,
        dimensions=[
            DimensionScore(key=key, label=label, score=value)
            for key, label, value in rubric.labelled(score_data.dimensions)
        ],
        strengths=score_data.strengths,
        improvements=score_data.improvements,
    )


async def _build_cv_context(session: InterviewSession) -> str:
    if not session.has_cv:
        return ""

    is_first_turn = sum(1 for m in session.messages if m["role"] == "assistant") == 0

    if is_first_turn and session.cv_full_text:
        return f"Full CV of the candidate:\n{session.cv_full_text}"

    # Use the last question as the retrieval query, not the user's answer,
    # so we surface CV sections relevant to the topic being probed.
    last_question = next(
        (m["content"] for m in reversed(session.messages) if m["role"] == "assistant"),
        "",
    )
    if not last_question:
        return ""

    try:
        return await rag.retrieve(session.session_id, last_question)
    except Exception as e:
        logger.warning(f"CV retrieval failed | session={session.session_id} | error={e}")
        return ""


async def _get_or_create_session(request: ChatRequest, db: Session) -> InterviewSession:
    if request.session_id:
        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.session_id == request.session_id)
            .with_for_update()
            .first()
        )
        if not session:
            logger.warning(f"Session not found: {request.session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    # Lazy creation: no session_id supplied. Derive a profile from whatever the
    # caller gave us (full job context if present, otherwise a role-only profile).
    if request.job_context:
        profile = await build_profile(request.job_context)
    else:
        role = request.role or settings.default_role
        from services import job_profile as job_profile_service

        profile = job_profile_service.minimal(role)

    session = InterviewSession(
        session_id=str(uuid.uuid4()),
        role=profile.role,
        num_questions=request.num_questions or settings.max_questions,
        messages=[],
        job_context=request.job_context,
        job_profile=profile.to_dict(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info(
        f"New session (via chat) | id={session.session_id} | "
        f"role={profile.role} | questions={session.num_questions}"
    )
    return session
