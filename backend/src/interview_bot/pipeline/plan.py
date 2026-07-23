"""Interview-plan extraction call: a JobProfile → an InterviewPlan blueprint.

Degrades to None (unplanned) on failure — not an error the caller must handle
specially: the interviewer then self-selects main-question topics, exactly as it
did before plans existed.
"""
from __future__ import annotations

from interview_bot import llm
from interview_bot.domain.plan import InterviewPlan, parse_plan
from interview_bot.domain.profile import JobProfile
from interview_bot.logger import logger
from interview_bot.prompts.plan import EXTRACT_SYSTEM, PlanExtraction, build_extraction_messages


async def build_plan(profile: JobProfile, num_questions: int) -> InterviewPlan | None:
    """Generate the coverage blueprint, degrading to None (unplanned) on failure."""
    try:
        extracted = await llm.parse(
            EXTRACT_SYSTEM,
            build_extraction_messages(profile, num_questions),
            PlanExtraction,
            max_tokens=1500,
            operation="build_plan",
        )
        return parse_plan(extracted.model_dump(), profile, num_questions)
    except Exception as e:
        logger.warning(
            f"Plan generation failed, proceeding without a plan | "
            f"error_type={type(e).__name__} | error={e}"
        )
        return None
