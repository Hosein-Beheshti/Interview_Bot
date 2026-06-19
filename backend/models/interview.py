from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import Vector
from datetime import datetime

from config import settings

Base = declarative_base()


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    session_id = Column(String, primary_key=True, index=True)
    role = Column(String, nullable=False)
    status = Column(String, default="created", nullable=False)
    num_questions = Column(Integer, default=5, nullable=False)
    messages = Column(JSON, default=list, nullable=False)
    answers_given = Column(Integer, default=0, nullable=False)
    # Count of distinct MAIN questions posed so far. Server-authoritative driver
    # of interview progression — follow-ups do not increment this.
    questions_asked = Column(Integer, default=0, nullable=False)
    # Follow-up turns spent on the current main question; reset to 0 whenever a
    # new main question is posed.
    followups_on_current = Column(Integer, default=0, nullable=False)
    # Per-answer score records (see services/summary.py for the shape). The
    # interview result summary is derived from this server-side.
    scores = Column(JSON, default=list, nullable=False)
    is_complete = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    cv_filename = Column(String, nullable=True)
    cv_indexed_at = Column(DateTime, nullable=True)
    cv_sections = Column(JSON, nullable=True)
    cv_full_text = Column(Text, nullable=True)
    job_context = Column(Text, nullable=True)
    job_profile = Column(JSON, nullable=True)

    @property
    def has_cv(self) -> bool:
        return self.cv_indexed_at is not None

    def resolve_profile(self):
        """Return the session's JobProfile, falling back to a role-only profile.

        Imported lazily to keep the ORM model free of service-layer dependencies.
        """
        from services import job_profile as job_profile_service

        if self.job_profile:
            return job_profile_service.JobProfile.from_dict(self.job_profile)
        return job_profile_service.minimal(self.role)

    @property
    def question_number(self) -> int:
        """1-based number of the main question currently in play (for display)."""
        return min(max(self.questions_asked, 1), self.num_questions)


class CVChunk(Base):
    __tablename__ = "cv_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String,
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    section = Column(String, nullable=False, default="general")
    content = Column(String, nullable=False)
    embedding = Column(Vector(settings.embedding_dim), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
