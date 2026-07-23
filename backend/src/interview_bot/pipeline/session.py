"""Interview-session setup flow.

Composes the async, LLM-backed steps that turn a pasted job description into a
persisted, ready-to-run session: extract the profile, design the plan, insert the
row. Plain persistence (fetch/insert) lives in
`interview_bot.persistence.sessions`; the extraction calls in
`interview_bot.pipeline.profile` / `interview_bot.pipeline.plan`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from interview_bot.config import settings
from interview_bot.domain.profile import minimal
from interview_bot.persistence import sessions as store
from interview_bot.persistence.models import InterviewSession
from interview_bot.pipeline.plan import build_plan
from interview_bot.pipeline.profile import build_profile
from interview_bot.telemetry import observe_turn, set_session


async def create_from_context(
    db: Session,
    *,
    job_context: str | None,
    role: str | None,
    num_questions: int | None = None,
) -> InterviewSession:
    """Create a session from a pasted job description, or a role-only fallback.

    Wrapped in a trace so the setup-time LLM calls (profile extraction, plan
    generation) are grouped and, once the session id exists, tagged onto it.
    """
    resolved_questions = num_questions or settings.max_questions
    async with observe_turn("session_create", metadata={"has_job_context": bool(job_context)}):
        if job_context:
            profile = await build_profile(job_context)
        else:
            profile = minimal(role or settings.default_role)
        interview_plan = await build_plan(profile, resolved_questions)
        session = store.create(
            db,
            profile=profile,
            num_questions=resolved_questions,
            job_context=job_context,
            interview_plan=interview_plan,
        )
        set_session(session.session_id)
        return session
