"""Job-profile extraction call: free-text job context → a normalized JobProfile.

Degrades to a role-only profile on any failure, so a flaky extraction never
blocks starting an interview.
"""
from __future__ import annotations

from interview_bot import llm
from interview_bot.config import settings
from interview_bot.domain.profile import JobProfile, minimal, parse_profile
from interview_bot.logger import logger
from interview_bot.prompts.profile import EXTRACT_SYSTEM, ProfileExtraction


async def build_profile(job_context: str) -> JobProfile:
    """Extract a structured profile from free text, degrading to role-only on failure."""
    try:
        extracted = await llm.parse(
            EXTRACT_SYSTEM,
            [{"role": "user", "content": job_context}],
            ProfileExtraction,
            operation="extract_profile",
        )
        return parse_profile(extracted.model_dump(), fallback_role=settings.default_role)
    except Exception as e:
        logger.warning(
            f"Job profile extraction failed, using fallback | "
            f"error_type={type(e).__name__} | error={e}"
        )
        return minimal(settings.default_role)
