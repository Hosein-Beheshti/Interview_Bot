"""Server-authoritative interview progression.

Pure domain logic that decides what the interviewer asks next and advances the
session's question bookkeeping. It depends only on interview state and the
scorer's control signals — never on the LLM, the DB, or the web layer — so it is
deterministic and unit-testable in isolation.

The state machine:

    main_question --(weak/promising answer, budget left)--> follow_up
    main_question --(answer ok, more questions left)-------> main_question
    main_question --(answer ok, last question done)--------> closing
    follow_up     --(budget left, still weak)--------------> follow_up
    follow_up     --(otherwise, more questions left)-------> main_question
    follow_up     --(otherwise, last question done)--------> closing

Follow-ups never consume a main-question slot; `max_followups_per_question` caps
how long the interview can dwell on one topic.
"""
from __future__ import annotations

from typing import Optional, Protocol

from config import settings
from logger import logger
from services import prompt
from services.evaluation import ScoreData


class InterviewState(Protocol):
    """The subset of session fields progression reads and mutates."""

    session_id: str
    num_questions: int
    questions_asked: int
    followups_on_current: int
    answers_given: int
    status: str
    is_complete: bool


def decide_next_turn(
    state: InterviewState, score: Optional[ScoreData]
) -> tuple[str, Optional[str]]:
    """Choose the next interviewer turn.

    Returns ``(mode, follow_up_kind)`` where ``mode`` is one of ``prompt.MODE_*``
    and ``follow_up_kind`` is set only for follow-ups. ``score is None`` means the
    candidate has not answered yet (the opening turn).
    """
    # Opening turn: no answer to react to — pose the first main question.
    if score is None:
        return prompt.MODE_MAIN, None

    can_follow_up = state.followups_on_current < settings.max_followups_per_question
    if can_follow_up:
        # The candidate did not attempt the question: down-shift to an easier
        # angle on the same topic rather than scoring a blank and moving on.
        if score.answer_type == "no_answer":
            return prompt.MODE_FOLLOW_UP, prompt.FOLLOW_UP_SIMPLIFY
        # A promising-but-shallow answer worth probing once more.
        if score.follow_up_recommended:
            return prompt.MODE_FOLLOW_UP, prompt.FOLLOW_UP_DEEPEN

    # Moving on from the current topic. If the last main question has already
    # been asked, the interview is over; otherwise pose the next main question.
    if state.questions_asked >= state.num_questions:
        return prompt.MODE_CLOSING, None
    return prompt.MODE_MAIN, None


def apply_turn(state: InterviewState, mode: str) -> None:
    """Advance interview state to reflect the turn just generated."""
    if mode == prompt.MODE_MAIN:
        state.questions_asked += 1
        state.followups_on_current = 0
    elif mode == prompt.MODE_FOLLOW_UP:
        state.followups_on_current += 1
    elif mode == prompt.MODE_CLOSING:
        state.status = "complete"
        state.is_complete = True
        logger.info(
            f"Interview complete | session={state.session_id} | "
            f"questions={state.questions_asked} | answers={state.answers_given}"
        )
