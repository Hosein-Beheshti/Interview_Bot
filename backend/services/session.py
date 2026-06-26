"""Interview session lifecycle: creation, lookup, and profile resolution.

The single home for how a session is born and fetched. Routes own HTTP policy
(e.g. 404 vs. create-new); this module owns the persistence and profile mechanics.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from config import settings
from logger import logger
from models.interview import InterviewSession
from services.integrations import llm
from services.observability import observe_turn, set_session
from services.interview import job_profile, plan
from services.interview.job_profile import JobProfile, ProfileExtraction
from services.interview.plan import InterviewPlan


def get(db: Session, session_id: str, *, lock: bool = False) -> InterviewSession | None:
    """Fetch a session by id. `lock=True` takes a row lock for the transaction."""
    query = db.query(InterviewSession).filter(InterviewSession.session_id == session_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def create(
    db: Session,
    *,
    profile: JobProfile,
    num_questions: int | None = None,
    job_context: str | None = None,
    interview_plan: InterviewPlan | None = None,
) -> InterviewSession:
    """Persist a new session for the given profile (num_questions: model default if None)."""
    session = InterviewSession(
        session_id=str(uuid.uuid4()),
        role=profile.role,
        messages=[],
        job_context=job_context,
        job_profile=profile.to_dict(),
    )
    if num_questions is not None:
        session.num_questions = num_questions
    if interview_plan is not None:
        session.interview_plan = interview_plan.to_dict()

    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info(
        f"Session created | id={session.session_id} | role={profile.role} | "
        f"skills={len(profile.key_skills)} | questions={session.num_questions} | "
        f"planned={interview_plan is not None}"
    )
    return session


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
            profile = job_profile.minimal(role or settings.default_role)
        interview_plan = await build_plan(profile, resolved_questions)
        session = create(
            db,
            profile=profile,
            num_questions=resolved_questions,
            job_context=job_context,
            interview_plan=interview_plan,
        )
        set_session(session.session_id)
        return session


async def build_plan(profile: JobProfile, num_questions: int) -> InterviewPlan | None:
    """Generate the coverage blueprint, degrading to None (unplanned) on failure.

    A None plan is not an error path the caller must handle specially: the
    interviewer simply falls back to choosing main-question topics itself, exactly
    as it did before plans existed.
    """
    try:
        extracted = await llm.parse(
            plan.EXTRACT_SYSTEM,
            plan.build_extraction_messages(profile, num_questions),
            plan.PlanExtraction,
            max_tokens=900,
            operation="build_plan",
        )
        return plan.parse_plan(extracted.model_dump(), profile, num_questions)
    except Exception as e:
        logger.warning(
            f"Plan generation failed, proceeding without a plan | "
            f"error_type={type(e).__name__} | error={e}"
        )
        return None


async def build_profile(job_context: str) -> JobProfile:
    """Extract a structured profile from free text, degrading to role-only on failure."""
    try:
        extracted = await llm.parse(
            job_profile.EXTRACT_SYSTEM,
            [{"role": "user", "content": job_context}],
            ProfileExtraction,
            operation="extract_profile",
        )
        return job_profile.parse_profile(
            extracted.model_dump(), fallback_role=settings.default_role
        )
    except Exception as e:
        logger.warning(
            f"Job profile extraction failed, using fallback | "
            f"error_type={type(e).__name__} | error={e}"
        )
        return job_profile.minimal(settings.default_role)


def resolve_profile(session: InterviewSession) -> JobProfile:
    """Reconstruct the session's JobProfile, falling back to a role-only profile."""
    if session.job_profile:
        return JobProfile.from_dict(session.job_profile)
    return job_profile.minimal(session.role)
