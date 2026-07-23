"""Server-authoritative interview progression — the pure FSM.

Decides what the interviewer asks next and advances the session's question
bookkeeping. Depends only on interview state and the scorer's control signals —
never on the LLM, the DB, config, the clock, or the web layer — so it is
deterministic and unit-testable with zero mocks. The one policy knob it needs,
`max_followups`, is passed in by the caller rather than read from config, which
is what keeps this module dependency-free.

The state machine:

    main_question --(weak/promising answer, budget left)--> follow_up
    main_question --(answer ok, more questions left)-------> main_question
    main_question --(answer ok, last question done)--------> closing
    follow_up     --(budget left, still weak)--------------> follow_up
    follow_up     --(otherwise, more questions left)-------> main_question
    follow_up     --(otherwise, last question done)--------> closing

Follow-ups never consume a main-question slot; `max_followups` caps how long the
interview can dwell on one topic.
"""
from __future__ import annotations

from typing import Protocol

from .scoring import ScoreData

# Interview turn modes — the FSM's output states. The interviewer prompt renders
# the matching instruction; the model never owns progression. Defined here (the
# FSM's home) and re-exported by the prompts layer.
MODE_MAIN = "main_question"
MODE_FOLLOW_UP = "follow_up"
MODE_CLOSING = "closing"

# Follow-up flavours.
FOLLOW_UP_DEEPEN = "deepen"
FOLLOW_UP_SIMPLIFY = "simplify"


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
    state: InterviewState, score: ScoreData | None, max_followups: int
) -> tuple[str, str | None]:
    """Choose the next interviewer turn.

    Returns ``(mode, follow_up_kind)`` where ``mode`` is one of ``MODE_*`` and
    ``follow_up_kind`` is set only for follow-ups. ``score is None`` means the
    candidate has not answered yet (the opening turn). ``max_followups`` is the
    cap on follow-up turns per main question.
    """
    # Opening turn: no answer to react to — pose the first main question.
    if score is None:
        return MODE_MAIN, None

    can_follow_up = state.followups_on_current < max_followups
    if can_follow_up:
        # The candidate did not attempt the question: down-shift to an easier
        # angle on the same topic rather than scoring a blank and moving on.
        if score.answer_type == "no_answer":
            return MODE_FOLLOW_UP, FOLLOW_UP_SIMPLIFY
        # A promising-but-shallow answer worth probing once more.
        if score.follow_up_recommended:
            return MODE_FOLLOW_UP, FOLLOW_UP_DEEPEN

    # Moving on from the current topic. If the last main question has already
    # been asked, the interview is over; otherwise pose the next main question.
    if state.questions_asked >= state.num_questions:
        return MODE_CLOSING, None
    return MODE_MAIN, None


def apply_turn(state: InterviewState, mode: str) -> None:
    """Advance interview state to reflect the turn just generated.

    Pure state mutation — the caller owns any logging or I/O that should
    accompany completion.
    """
    if mode == MODE_MAIN:
        state.questions_asked += 1
        state.followups_on_current = 0
    elif mode == MODE_FOLLOW_UP:
        state.followups_on_current += 1
    elif mode == MODE_CLOSING:
        state.status = "complete"
        state.is_complete = True
