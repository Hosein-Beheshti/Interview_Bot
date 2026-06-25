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
from services.interview import job_profile
from services.interview.job_profile import JobProfile, ProfileExtraction


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

    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info(
        f"Session created | id={session.session_id} | role={profile.role} | "
        f"skills={len(profile.key_skills)} | questions={session.num_questions}"
    )
    return session


async def create_from_context(
    db: Session,
    *,
    job_context: str | None,
    role: str | None,
    num_questions: int | None = None,
) -> InterviewSession:
    """Create a session from a pasted job description, or a role-only fallback."""
    if job_context:
        profile = await build_profile(job_context)
    else:
        profile = job_profile.minimal(role or settings.default_role)
    return create(db, profile=profile, num_questions=num_questions, job_context=job_context)


async def build_profile(job_context: str) -> JobProfile:
    """Extract a structured profile from free text, degrading to role-only on failure."""
    try:
        extracted = await llm.parse(
            job_profile.EXTRACT_SYSTEM,
            [{"role": "user", "content": job_context}],
            ProfileExtraction,
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
