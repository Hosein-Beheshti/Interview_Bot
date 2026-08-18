"""Answer-scoring orchestration.

Assembles the scorer prompt, calls the LLM, and parses the result into the
domain `ScoreData`. This is the single scoring path shared by the live interview
(`score_answer`, session-aware) and the offline eval harness (`score`, pure), so
the eval measures exactly what production runs.
"""
from __future__ import annotations

from interview_bot import llm
from interview_bot.config import settings
from interview_bot.domain import rubric
from interview_bot.domain.plan import PlanSlot
from interview_bot.domain.profile import JobProfile, build_context
from interview_bot.domain.scoring import ScoreData, parse_score
from interview_bot.domain.transcript import last_assistant
from interview_bot.logger import logger
from interview_bot.prompts import scoring as scorer_prompt


async def score(
    profile: JobProfile,
    question: str,
    answer: str,
    *,
    reference_points: tuple[str, ...] = (),
) -> ScoreData | None:
    """Score one answer against the rubric. Pure (no session/DB); never raises.

    `reference_points` are the key points a strong answer should cover; when
    present they ground the judgement (reference-guided scoring).
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"{build_context(profile)}\n\n"
                f"Interview question: {question}\n"
                f"Candidate's answer: {answer}"
                f"{scorer_prompt.reference_block(reference_points)}"
            ),
        }
    ]
    try:
        raw = await llm.generate_structured(
            "", messages, rubric.build_score_format(),
            cache_prefix=scorer_prompt.SCORE_CACHE_PREFIX,
            max_tokens=settings.score_max_tokens,
            operation="score_answer",
            # Versions ride on the trace only (not the request bytes), so every
            # scored answer is traceable to the prompt + rubric that produced it.
            trace_metadata={
                "prompt_version": scorer_prompt.PROMPT_VERSION,
                "rubric_version": rubric.RUBRIC_VERSION,
            },
        )
        return parse_score(raw)
    except Exception as e:
        logger.warning(f"Scoring failed | error_type={type(e).__name__} | error={e}")
        return None


async def score_answer(
    session, profile: JobProfile, slot: PlanSlot | None = None
) -> ScoreData | None:
    """Score the candidate's most recent answer. Never raises (returns None).

    Called after the answer is appended but before the reply is generated, so the
    answer is the last message and the question is the most recent assistant turn.
    `slot` is the blueprint slot for the answered question; its key points seed
    reference-guided grading (absent for unplanned sessions).
    """
    user_answer = session.messages[-1]["content"]
    last_question = last_assistant(session.messages[:-1]) or ""
    reference_points = slot.key_points if slot else ()
    score_data = await score(profile, last_question, user_answer, reference_points=reference_points)
    if score_data is not None:
        logger.info(
            f"Score | session={session.session_id} | q={session.answers_given} | "
            f"overall={score_data.overall} | answer_type={score_data.answer_type} | "
            f"follow_up={score_data.follow_up_recommended}"
        )
        logger.debug(f"Critique | session={session.session_id} | {score_data.critique}")
    return score_data
