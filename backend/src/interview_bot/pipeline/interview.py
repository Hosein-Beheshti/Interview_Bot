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
from interview_bot.domain.plan import PlanSlot
from interview_bot.domain.profile import JobProfile
from interview_bot.domain.scoring import ScoreData
from interview_bot.domain.transcript import last_assistant
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


@dataclass
class _PendingTurn:
    """A decided turn, before the interviewer has spoken.

    Everything the server controls — scoring, the progression decision, and for a
    closing turn the finished reply — is settled here. `prompt` is set only when
    the model still has to produce the text, which is what lets the buffered and
    streaming paths share every decision and differ solely in delivery.
    """

    mode: str
    score_data: ScoreData | None
    score_record: dict | None
    summary: dict | None
    reply: str | None
    prompt: _TurnPrompt | None


@dataclass
class _TurnPrompt:
    """The assembled inputs for one interviewer generation."""

    instruction: str
    cache_prefix: str


def build_turn_prompt(
    profile: JobProfile,
    mode: str,
    follow_up_kind: str | None,
    *,
    slot: PlanSlot | None,
    current_topic: str | None,
    candidate_name: str | None,
    cv_context: str,
    question_number: int,
    num_questions: int,
) -> _TurnPrompt:
    """Assemble the interviewer's prompt for one turn. Pure — no session, no I/O.

    Shared by `_decide_turn` (live turns) and the generator eval harness, so the
    eval measures exactly the prompt bytes production sends to the model.
    """
    stable = interviewer.build_stable_prompt(
        profile, num_questions=num_questions, cv_context=cv_context
    )
    turn = interviewer.turn_instruction(
        mode,
        question_number,
        follow_up_kind,
        current_topic=current_topic,
        slot=slot,
        candidate_name=candidate_name,
    )
    return _TurnPrompt(instruction=turn, cache_prefix=stable)


async def run_turn(session, message: str, profile: JobProfile) -> TurnResult:
    """Advance the interview by one turn. Mutates `session`; never commits.

    Raises `InterviewError` if reply generation fails (the route maps it to 502
    and does not commit, so the in-memory mutations are discarded cleanly).
    """
    pending = await _decide_turn(session, message, profile)
    if pending.prompt is None:
        return _finish_turn(session, pending, pending.reply or "")

    try:
        reply = await llm.generate(
            session.messages,
            pending.prompt.instruction,
            cache_prefix=pending.prompt.cache_prefix,
            operation="interviewer_turn",
        )
    except Exception as e:
        logger.error(f"LLM generation failed | session={session.session_id} | error={e}")
        raise InterviewError("AI service unavailable") from e

    return _finish_turn(session, pending, reply)


async def stream_turn(session, message: str, profile: JobProfile):
    """Advance the interview by one turn, yielding the reply as it is produced.

    Identical to `run_turn` in every decision it makes — same scoring, same
    progression, same assembled prompt — and identical in the text it ends up
    persisting. Yields `("score", ScoreData | None)` once the previous answer has
    been graded, then `("delta", str)` per chunk, then `("result", TurnResult)`.

    The score is emitted before generation starts because it is already known by
    then: the candidate sees their grade for the last answer while the next
    question is still being written.
    """
    pending = await _decide_turn(session, message, profile)
    yield "score", pending.score_data

    if pending.prompt is None:
        yield "delta", pending.reply or ""
        yield "result", _finish_turn(session, pending, pending.reply or "")
        return

    chunks: list[str] = []
    try:
        async for chunk in llm.stream(
            session.messages,
            pending.prompt.instruction,
            cache_prefix=pending.prompt.cache_prefix,
            operation="interviewer_turn",
        ):
            chunks.append(chunk)
            yield "delta", chunk
    except Exception as e:
        logger.error(f"LLM streaming failed | session={session.session_id} | error={e}")
        raise InterviewError("AI service unavailable") from e

    yield "result", _finish_turn(session, pending, "".join(chunks))


async def _decide_turn(session, message: str, profile: JobProfile) -> _PendingTurn:
    """Score the answer, pick the next move, and assemble the prompt for it."""
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

    score_record = (
        _score_record(answered_q, answered_follow_up, score_data)
        if score_data is not None
        else None
    )

    if mode == progression.MODE_CLOSING:
        # The closing turn is server-owned and deterministic — rendered from the
        # final results, never a model turn — so it can neither ask a further
        # question nor be derailed by an instruction embedded in an answer.
        final_scores = session.scores + ([score_record] if score_record else [])
        summary_data = summary.build_summary(profile.role, final_scores)
        return _PendingTurn(
            mode=mode,
            score_data=score_data,
            score_record=score_record,
            summary=summary_data,
            reply=summary.closing_message(summary_data),
            prompt=None,
        )

    try:
        # The role/rules/CV guidance is identical every turn — send it as a
        # cached prefix so re-sending a full CV each turn is nearly free. Only
        # the turn instruction (which question, follow-up) varies.
        cv_context = await build_cv_context(session)
        # For a main question, pin the topic to its blueprint slot (if planned);
        # a follow-up ignores the slot and stays on the current topic.
        next_question_number = session.questions_asked + 1
        slot = (
            interview_plan.slot_for(next_question_number)
            if interview_plan and mode == interviewer.MODE_MAIN
            else None
        )
        prompt = build_turn_prompt(
            profile,
            mode,
            follow_up_kind,
            slot=slot,
            current_topic=last_assistant(session.messages),
            candidate_name=session.candidate_name,
            cv_context=cv_context,
            question_number=next_question_number,
            num_questions=session.num_questions,
        )
    except Exception as e:
        logger.error(f"Turn prompt assembly failed | session={session.session_id} | error={e}")
        raise InterviewError("AI service unavailable") from e

    return _PendingTurn(
        mode=mode,
        score_data=score_data,
        score_record=score_record,
        summary=None,
        reply=None,
        prompt=prompt,
    )


def _finish_turn(session, pending: _PendingTurn, reply: str) -> TurnResult:
    """Record the interviewer's reply and advance the session's counters."""
    session.messages.append({"role": "assistant", "content": reply})
    flag_modified(session, "messages")

    if session.status == "created":
        session.status = "active"

    progression.apply_turn(session, pending.mode)
    if session.is_complete:
        logger.info(
            f"Interview complete | session={session.session_id} | "
            f"questions={session.questions_asked} | answers={session.answers_given}"
        )

    # Persist the score only now that the turn has fully succeeded, so a failed
    # generation followed by a retry cannot double-record an answer.
    if pending.score_record is not None:
        session.scores = session.scores + [pending.score_record]
        flag_modified(session, "scores")

    return TurnResult(
        reply=reply,
        mode=pending.mode,
        score_data=pending.score_data,
        summary=pending.summary,
    )


def _score_record(q: int | None, follow_up: bool | None, score_data: ScoreData) -> dict:
    """The per-answer record persisted on the session (see domain/summary.py)."""
    return {
        "q": q,
        "follow_up": follow_up,
        "score": score_data.overall,
        "strengths": score_data.strengths,
        "improvements": score_data.improvements,
    }
