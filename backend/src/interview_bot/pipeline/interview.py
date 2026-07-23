"""Per-turn interview engine.

Owns what happens on each /chat turn: score the candidate's previous answer, let
the progression state machine choose the next move, generate the interviewer's
reply, and record the result. It operates on the in-memory `session` object and
external services — it does not touch HTTP or the DB transaction; the route owns
committing and DTO mapping.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm.attributes import flag_modified

from interview_bot import llm
from interview_bot.config import settings
from interview_bot.domain import plan, progression, summary
from interview_bot.domain.profile import JobProfile
from interview_bot.domain.scoring import ScoreData
from interview_bot.logger import logger
from interview_bot.pipeline.scoring import score_answer
from interview_bot.prompts import interviewer
from interview_bot.retrieval.cv_context import build_cv_context


class InterviewError(RuntimeError):
    """Raised when the interviewer's reply cannot be generated."""


@dataclass
class TurnResult:
    reply: str
    mode: str
    score_data: ScoreData | None
    summary: dict | None


async def run_turn(session, message: str, profile: JobProfile) -> TurnResult:
    """Advance the interview by one turn. Mutates `session`; never commits.

    Raises `InterviewError` if reply generation fails (the route maps it to 502
    and does not commit, so the in-memory mutations are discarded cleanly).
    """
    is_first_message = len(session.messages) == 0
    interview_plan = plan.resolve(session)

    session.messages.append({"role": "user", "content": message})
    flag_modified(session, "messages")

    # Score the candidate's answer first (when there is one). The control signals
    # drive the next-turn decision. Capture which question is being answered BEFORE
    # progression mutates the counters.
    score_data = None
    answered_q = answered_follow_up = None
    if not is_first_message:
        session.answers_given += 1
        answered_q = session.questions_asked
        answered_follow_up = session.followups_on_current > 0
        # Grade against the answered question's blueprint slot (reference-guided).
        # Follow-ups have no slot of their own; they reuse the current topic's slot.
        answered_slot = interview_plan.slot_for(answered_q) if interview_plan else None
        score_data = await score_answer(session, profile, slot=answered_slot)

    mode, follow_up_kind = progression.decide_next_turn(
        session, score_data, settings.max_followups_per_question
    )

    try:
        cv_context = await build_cv_context(session)
        # The role/rules/CV guidance is identical every turn — send it as a cached
        # prefix so re-sending a full CV each turn is nearly free. Only the turn
        # instruction (which question, follow-up vs. closing) varies.
        stable = interviewer.build_stable_prompt(
            profile, num_questions=session.num_questions, cv_context=cv_context
        )
        # For a main question, pin the topic to its blueprint slot (if planned).
        # Follow-ups and the closing turn ignore the slot — they stay on the
        # current topic or wrap up.
        next_question_number = session.questions_asked + 1
        slot = (
            interview_plan.slot_for(next_question_number)
            if interview_plan and mode == interviewer.MODE_MAIN
            else None
        )
        turn = interviewer.turn_instruction(
            mode,
            next_question_number,
            follow_up_kind,
            current_topic=_last_question(session),
            slot=slot,
        )
        reply = await llm.generate(
            session.messages, turn, cache_prefix=stable, operation="interviewer_turn"
        )
    except Exception as e:
        logger.error(f"LLM generation failed | session={session.session_id} | error={e}")
        raise InterviewError("AI service unavailable") from e

    session.messages.append({"role": "assistant", "content": reply})
    flag_modified(session, "messages")

    if session.status == "created":
        session.status = "active"

    progression.apply_turn(session, mode)
    if session.is_complete:
        logger.info(
            f"Interview complete | session={session.session_id} | "
            f"questions={session.questions_asked} | answers={session.answers_given}"
        )

    # Persist the score only now that the turn has fully succeeded, so a failed
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

    summary_data = summary.build_summary(profile.role, session.scores) if session.is_complete else None
    return TurnResult(reply=reply, mode=mode, score_data=score_data, summary=summary_data)


def _last_question(session) -> str | None:
    """The most recent question the interviewer asked (for follow-up anchoring)."""
    return next(
        (m["content"] for m in reversed(session.messages) if m["role"] == "assistant"),
        None,
    )
