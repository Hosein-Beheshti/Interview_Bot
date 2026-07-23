"""Interview-session persistence: fetch, insert, and profile reconstruction.

Plain database mechanics over `InterviewSession`. Routes own HTTP policy (404 vs.
create-new); the async setup flow that composes profile + plan extraction before
insert lives in `interview_bot.pipeline.session`.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from interview_bot.domain.plan import InterviewPlan
from interview_bot.domain.profile import JobProfile, minimal
from interview_bot.logger import logger
from interview_bot.persistence.models import InterviewSession


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


def resolve_profile(session: InterviewSession) -> JobProfile:
    """Reconstruct the session's JobProfile, falling back to a role-only profile."""
    if session.job_profile:
        return JobProfile.from_dict(session.job_profile)
    return minimal(session.role)
