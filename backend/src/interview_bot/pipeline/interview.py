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
from interview_bot.domain import plan, progression, summary, turn_quality
from interview_bot.domain.plan import PlanSlot
from interview_bot.domain.profile import JobProfile
from interview_bot.domain.scoring import ScoreData
from interview_bot.domain.transcript import last_assistant
from interview_bot.logger import logger
from interview_bot.pipeline.scoring import score_answer
from interview_bot.prompts import interviewer
from interview_bot.retrieval.cv_context import CVContext, build_cv_context


class InterviewError(RuntimeError):
    """Raised when the interviewer's reply cannot be generated."""


@dataclass
class TurnResult:
    reply: str
    mode: str
    score_data: ScoreData | None
    summary: dict | None
    # Which answer `score_data` grades: the main question it belongs to, and
    # whether it was a follow-up. The route needs both to persist the score for
    # later calibration (see `persistence.models.AnswerScore`).
    answered_question: int | None = None
    answered_follow_up: bool = False


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
    # The main-question number this turn carries, for the label contract enforced
    # in `_finish_turn`. Meaningless for a follow-up or the closing turn.
    question_number: int = 0
    answered_question: int | None = None
    answered_follow_up: bool = False


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
    cv_context: CVContext,
    question_number: int,
    num_questions: int,
) -> _TurnPrompt:
    """Assemble the interviewer's prompt for one turn. Pure — no session, no I/O.

    Shared by `_decide_turn` (live turns) and the generator eval harness, so the
    eval measures exactly the prompt bytes production sends to the model.

    A stable CV context (the full-text path) joins the cacheable prefix; a
    volatile one (per-question retrieval) leads the turn instruction instead. The
    assembled text is the same in both cases — only the cache breakpoint moves.
    """
    stable = interviewer.build_stable_prompt(
        profile,
        num_questions=num_questions,
        cv_context=cv_context.text if cv_context.stable else "",
    )
    turn = interviewer.turn_instruction(
        mode,
        question_number,
        follow_up_kind,
        current_topic=current_topic,
        slot=slot,
        candidate_name=candidate_name,
    )
    if cv_context and not cv_context.stable:
        turn = f"{interviewer.cv_block(cv_context.text)}\n\n{turn}"
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
        session,
        score_data,
        settings.max_followups_per_question,
        answered=not is_first_message,
    )

    score_record = None
    if not is_first_message:
        # An answer the evaluator could not grade is still recorded, as a gap.
        # Dropping it would quietly shrink the denominator of the final score.
        score_record = (
            _score_record(answered_q, answered_follow_up, score_data)
            if score_data is not None
            else _unscored_record(answered_q, answered_follow_up)
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
            answered_question=answered_q,
            answered_follow_up=bool(answered_follow_up),
        )

    try:
        # For a main question, pin the topic to its blueprint slot (if planned);
        # a follow-up ignores the slot and stays on the current topic.
        next_question_number = session.questions_asked + 1
        slot = (
            interview_plan.slot_for(next_question_number)
            if interview_plan and mode == interviewer.MODE_MAIN
            else None
        )
        current_topic = last_assistant(session.messages)
        # The role/rules guidance is identical every turn — send it as a cached
        # prefix so re-sending a full CV each turn is nearly free. Only the turn
        # instruction (which question, follow-up) varies.
        cv_context = await build_cv_context(session, _retrieval_topic(mode, slot, current_topic))
        prompt = build_turn_prompt(
            profile,
            mode,
            follow_up_kind,
            slot=slot,
            current_topic=current_topic,
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
        question_number=next_question_number,
        answered_question=answered_q,
        answered_follow_up=bool(answered_follow_up),
    )


def _retrieval_topic(mode: str, slot: PlanSlot | None, current_topic: str | None) -> str | None:
    """What the CV should be searched against for the turn about to be generated.

    A main question moves to a NEW topic, so the query is its planned slot, not
    the question just asked — searching the CV for the topic being left behind
    retrieves the wrong excerpts. A follow-up genuinely stays put, so there the
    previous question is the right query.
    """
    if mode == interviewer.MODE_MAIN:
        return f"{slot.skill} {slot.intent}".strip() if slot else None
    return current_topic


def _finish_turn(session, pending: _PendingTurn, reply: str) -> TurnResult:
    """Record the interviewer's reply and advance the session's counters.

    The reply is forced to satisfy the label contract first. The FSM is
    server-authoritative, but the candidate reads the model's text — so if the
    model numbers a question differently from the server, or answers a follow-up
    with a fresh numbered question, what the candidate sees desynchronises from
    the interview the server is running. The repair is deterministic and costs
    nothing (see `turn_quality.repair`).
    """
    reply = _enforce_format(session, pending, reply)

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
        answered_question=pending.answered_question,
        answered_follow_up=pending.answered_follow_up,
    )


def _enforce_format(session, pending: _PendingTurn, reply: str) -> str:
    """Apply the label contract to a generated reply, logging any repair.

    A repair means the model drifted from an explicit instruction, which is worth
    seeing in the logs even though the turn itself is now correct.
    """
    repaired, kind = turn_quality.repair(pending.mode, pending.question_number, reply)
    if kind:
        logger.warning(
            f"Turn format repaired | session={session.session_id} | "
            f"mode={pending.mode} | q={pending.question_number} | repair={kind}"
        )
    return repaired


def _score_record(q: int | None, follow_up: bool | None, score_data: ScoreData) -> dict:
    """The per-answer record persisted on the session (see domain/summary.py)."""
    return {
        "q": q,
        "follow_up": follow_up,
        "score": score_data.overall,
        "strengths": score_data.strengths,
        "improvements": score_data.improvements,
    }


def _unscored_record(q: int | None, follow_up: bool | None) -> dict:
    """The record for an answer the evaluator could not grade."""
    return {"q": q, "follow_up": follow_up, "unscored": True}
