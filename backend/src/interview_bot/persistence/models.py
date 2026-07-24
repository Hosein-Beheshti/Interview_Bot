"""SQLAlchemy ORM entities (declarative, 2.0 typed-`Mapped` style).

Typed columns so a persisted field reads as its Python type (`str`, not
`Column[str]`) across the app — the boundary between storage and the rest of the
code is fully typed. Table shape and defaults are unchanged.
"""
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from interview_bot.config import settings

# Timestamps are stored with a zone and written as aware UTC. Retention and CV
# freshness compare them against `datetime.now(UTC)`; a naive column would make
# that comparison depend on the server's local zone.
_UTC_TIMESTAMP = DateTime(timezone=True)


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    session_id: Mapped[str] = mapped_column(primary_key=True, index=True)
    role: Mapped[str]
    status: Mapped[str] = mapped_column(default="created")
    num_questions: Mapped[int] = mapped_column(default=5)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    answers_given: Mapped[int] = mapped_column(default=0)
    # Count of distinct MAIN questions posed so far. Server-authoritative driver
    # of interview progression — follow-ups do not increment this.
    questions_asked: Mapped[int] = mapped_column(default=0)
    # Follow-up turns spent on the current main question; reset to 0 whenever a
    # new main question is posed.
    followups_on_current: Mapped[int] = mapped_column(default=0)
    # Per-answer score records (see domain/summary.py for the shape). The
    # interview result summary is derived from this server-side.
    scores: Mapped[list] = mapped_column(JSON, default=list)
    is_complete: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, default=_now)
    cv_filename: Mapped[str | None] = mapped_column(default=None)
    cv_indexed_at: Mapped[datetime | None] = mapped_column(_UTC_TIMESTAMP, default=None)
    cv_sections: Mapped[Any | None] = mapped_column(JSON, default=None)
    cv_full_text: Mapped[str | None] = mapped_column(Text, default=None)
    # Best-effort first name parsed from the CV, for the opening greeting. Null
    # when no CV is uploaded or the heuristic couldn't find a name line.
    candidate_name: Mapped[str | None] = mapped_column(default=None)
    job_context: Mapped[str | None] = mapped_column(Text, default=None)
    job_profile: Mapped[Any | None] = mapped_column(JSON, default=None)
    # Upfront coverage blueprint: one slot per main question (see
    # domain/plan.py). Null for sessions created before planning existed or when
    # generation failed — the interviewer self-selects topics then.
    interview_plan: Mapped[Any | None] = mapped_column(JSON, default=None)

    @property
    def has_cv(self) -> bool:
        return self.cv_indexed_at is not None

    @property
    def question_number(self) -> int:
        """1-based number of the main question currently in play (for display)."""
        return min(max(self.questions_asked, 1), self.num_questions)


class UsageCounter(Base):
    """One fixed window of one metered thing, for rate limits and the spend budget.

    `subject` is whoever is being metered — a client IP for a rate limit, or the
    literal "global" for an instance-wide budget.
    """

    __tablename__ = "usage_counters"

    bucket: Mapped[str] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, primary_key=True)
    # Tokens overflow a 32-bit counter within a day of ordinary traffic.
    amount: Mapped[int] = mapped_column(BigInteger, default=0)


class CVChunk(Base):
    __tablename__ = "cv_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int]
    section: Mapped[str] = mapped_column(default="general")
    content: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    created_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, default=_now)
