"""Interview-session persistence: fetch, insert, delete, and profile reconstruction.

Plain database mechanics over `InterviewSession`. Routes own HTTP policy (404 vs.
create-new); the async setup flow that composes profile + plan extraction before
insert lives in `interview_bot.pipeline.session`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete as delete_rows
from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_bot.domain.plan import InterviewPlan
from interview_bot.domain.profile import JobProfile, minimal
from interview_bot.logger import logger
from interview_bot.persistence.models import CVChunk, InterviewSession


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


def delete(db: Session, session_id: str) -> bool:
    """Erase a session and its indexed CV chunks. False if it did not exist.

    Chunks are removed explicitly rather than left to the foreign key's ON DELETE
    CASCADE: tables created before that constraint existed would silently keep
    their embeddings, and this is the path that has to actually erase a person's
    CV on request.
    """
    session = get(db, session_id)
    if session is None:
        return False
    db.execute(delete_rows(CVChunk).where(CVChunk.session_id == session_id))
    db.delete(session)
    db.commit()
    logger.info(f"Session deleted | id={session_id}")
    return True


def delete_created_before(db: Session, cutoff: datetime) -> int:
    """Erase every session created before `cutoff`. Returns how many were removed.

    The retention sweep. Uploaded CVs are personal data belonging to people who
    tried a demo once, so sessions are not kept indefinitely.
    """
    expired = list(
        db.execute(
            select(InterviewSession.session_id).where(InterviewSession.created_at < cutoff)
        ).scalars()
    )
    if not expired:
        return 0
    db.execute(delete_rows(CVChunk).where(CVChunk.session_id.in_(expired)))
    db.execute(delete_rows(InterviewSession).where(InterviewSession.session_id.in_(expired)))
    db.commit()
    logger.info(f"Retention sweep | deleted={len(expired)} | cutoff={cutoff.isoformat()}")
    return len(expired)


def resolve_profile(session: InterviewSession) -> JobProfile:
    """Reconstruct the session's JobProfile, falling back to a role-only profile."""
    if session.job_profile:
        return JobProfile.from_dict(session.job_profile)
    return minimal(session.role)
