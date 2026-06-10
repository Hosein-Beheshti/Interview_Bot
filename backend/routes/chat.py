import uuid
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from models.schemas import ChatRequest, ChatResponse, ScoreResult
from models.interview import InterviewSession
from services import llm, prompt, evaluation, rag
from database import get_db
from logger import logger

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    session = _get_or_create_session(request, db)
    logger.info(f"Chat request | session={session.session_id} | status={session.status} | answers={session.answers_given}")

    if session.status == "complete":
        logger.warning(f"Attempt to use completed session: {session.session_id}")
        raise HTTPException(status_code=400, detail="Interview already completed")

    is_first_message = len(session.messages) == 0

    if session.status == "created" and not is_first_message:
        session.status = "active"

    session.messages.append({"role": "user", "content": request.message})
    flag_modified(session, "messages")

    try:
        cv_context = await _build_cv_context(session, request.message)
        system = prompt.get_system_prompt(session.role, num_questions=session.num_questions, cv_context=cv_context)
        reply = await llm.chat(session.messages, system)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise HTTPException(status_code=502, detail="AI service unavailable")

    session.messages.append({"role": "assistant", "content": reply})
    flag_modified(session, "messages")

    if session.status == "created":
        session.status = "active"

    score_result = None
    if not is_first_message:
        session.answers_given += 1
        user_answer = session.messages[-2]["content"]
        last_question = next(
            (m["content"] for m in reversed(session.messages[:-2]) if m["role"] == "assistant"),
            "",
        )
        try:
            tool_input = await llm.score(last_question, user_answer, session.role)
            score_data = evaluation.parse_score(tool_input)
            if score_data:
                score_result = ScoreResult(
                    score=score_data.score,
                    strengths=score_data.strengths,
                    improvements=score_data.improvements,
                )
                logger.info(f"Score | session={session.session_id} | score={score_data.score}")
        except Exception as e:
            logger.warning(f"Scoring failed | session={session.session_id} | error={e}")

        if session.answers_given >= session.num_questions:
            session.status = "complete"
            session.is_complete = True
            logger.info(f"Interview complete | session={session.session_id} | answers={session.answers_given}")

    db.add(session)
    db.commit()
    db.refresh(session)

    return ChatResponse(
        reply=reply,
        session_id=session.session_id,
        status=session.status,
        question_number=session.question_number,
        is_complete=session.is_complete,
        score=score_result,
    )


async def _build_cv_context(session: InterviewSession, user_message: str) -> str:
    if not session.has_cv:
        return ""

    is_first_turn = len(session.messages) <= 1

    if is_first_turn and session.cv_full_text:
        return f"Full CV of the candidate:\n{session.cv_full_text}"

    try:
        return await rag.retrieve(session.session_id, user_message)
    except Exception as e:
        logger.warning(f"CV retrieval failed | session={session.session_id} | error={e}")
        return ""


def _get_or_create_session(request: ChatRequest, db: Session) -> InterviewSession:
    if not request.session_id:
        session = InterviewSession(
            session_id=str(uuid.uuid4()),
            role=request.role,
            num_questions=request.num_questions,
            messages=[],
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info(f"New session | id={session.session_id} | role={request.role} | questions={request.num_questions}")
        return session

    session = db.query(InterviewSession).filter(
        InterviewSession.session_id == request.session_id
    ).first()
    if not session:
        logger.warning(f"Session not found: {request.session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    return session
