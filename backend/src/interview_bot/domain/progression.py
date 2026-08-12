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

An answer the scorer could not grade is a third input, distinct from "no answer
yet": the interview must still advance (and still be able to end), it just has no
signal to base a follow-up on. Conflating the two would let an evaluator outage
push the interview past its last question — see `decide_next_turn`.
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
    state: InterviewState,
    score: ScoreData | None,
    max_followups: int,
    *,
    answered: bool,
) -> tuple[str, str | None]:
    """Choose the next interviewer turn.

    Returns ``(mode, follow_up_kind)`` where ``mode`` is one of ``MODE_*`` and
    ``follow_up_kind`` is set only for follow-ups. ``max_followups`` is the cap on
    follow-up turns per main question.

    ``answered`` says whether the candidate has just answered a question;
    ``score`` is the grade for that answer, or None when grading failed. The two
    are separate on purpose — ``answered=False`` is the opening turn and always
    yields the first main question, whereas an ungraded answer still consumed a
    question and must still be able to end the interview.
    """
    # Opening turn: no answer to react to — pose the first main question.
    if not answered:
        return MODE_MAIN, None

    # The answer stands, but the evaluator failed to grade it. There is no signal
    # to justify a follow-up, so advance as if the topic were covered.
    if score is None:
        return _advance(state)

    can_follow_up = state.followups_on_current < max_followups
    if can_follow_up:
        # The candidate did not attempt the question: down-shift to an easier
        # angle on the same topic rather than scoring a blank and moving on.
        if score.answer_type == "no_answer":
            return MODE_FOLLOW_UP, FOLLOW_UP_SIMPLIFY
        # A promising-but-shallow answer worth probing once more.
        if score.follow_up_recommended:
            return MODE_FOLLOW_UP, FOLLOW_UP_DEEPEN

    return _advance(state)


def _advance(state: InterviewState) -> tuple[str, str | None]:
    """Move on from the current topic: the next main question, or the close.

    The single exit from a finished topic, so every path that stops dwelling on
    one question is bound by the same question budget.
    """
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
