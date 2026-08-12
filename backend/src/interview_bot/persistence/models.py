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
    # Owner. Nullable so rows created before accounts existed stay reachable
    # (unchanged status quo) — only sessions with a recorded owner become
    # access-controlled. SET NULL, not CASCADE: deleting an account should not
    # destroy transcripts; the retention sweep erases them on its own schedule.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

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


class User(Base):
    __tablename__ = "users"

    # String UUID PK, matching InterviewSession's convention (not CVChunk's
    # autoincrement-int style, which is reserved for pure child rows never
    # referenced externally).
    id: Mapped[str] = mapped_column(primary_key=True)
    # Google's stable per-account id (the `sub` claim) — the real identity.
    # Email is not the identity: Google lets it change.
    google_sub: Mapped[str] = mapped_column(unique=True, index=True)
    email: Mapped[str] = mapped_column(index=True)
    display_name: Mapped[str | None] = mapped_column(default=None)
    picture_url: Mapped[str | None] = mapped_column(default=None)
    credits: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, default=_now)
    last_login_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, default=_now)


class UserSession(Base):
    """A logged-in browser session — what the cookie actually names.

    Not folded into User: one account may hold several concurrent
    UserSessions (multiple browsers/devices), each independently revocable by
    deleting its row.
    """

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SHA-256 of the raw bearer token — never the token itself. A DB dump,
    # backup, or stray read must not hand out a usable session; verifying a
    # presented cookie is just re-hashing and an indexed lookup, so this costs
    # nothing at runtime.
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, default=_now)
    expires_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP)


class AnswerScore(Base):
    """One evaluator judgement, kept in full for calibration.

    The result the candidate sees comes from `InterviewSession.scores`, which
    holds only the roll-up (overall, strengths, improvements). That is enough to
    render an interview and not enough to tell whether the scoring is any good.
    This table keeps what the evaluator actually produced — per-dimension scores,
    the answer classification, and the critique the scores were derived from —
    stamped with the prompt and rubric versions that produced them, since results
    across versions are not comparable.

    Nothing in the request path reads it: it is written after a turn succeeds and
    queried offline, so scorer drift can be measured on real interviews instead
    of only on the golden set. Cascades with the session, so the retention purge
    and an explicit session delete both erase it.
    """

    __tablename__ = "answer_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"), index=True
    )
    # Which main question was answered, and whether this was its follow-up —
    # together these locate the answer within the interview.
    question_number: Mapped[int | None] = mapped_column(default=None)
    follow_up: Mapped[bool] = mapped_column(default=False)
    overall: Mapped[int]
    # {dimension_key: score}, per `domain.rubric.DEFAULT_RUBRIC`.
    dimensions: Mapped[Any] = mapped_column(JSON, default=dict)
    answer_type: Mapped[str]
    follow_up_recommended: Mapped[bool] = mapped_column(default=False)
    # The evaluator's reasoning, written before the scores. Never shown to the
    # candidate; the highest-signal field when a score looks wrong.
    critique: Mapped[str] = mapped_column(Text, default="")
    # Content-derived hashes (`prompts.scoring.PROMPT_VERSION`,
    # `domain.rubric.RUBRIC_VERSION`) plus the model that graded. A score is only
    # comparable to another with all three equal.
    prompt_version: Mapped[str]
    rubric_version: Mapped[str]
    model: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(_UTC_TIMESTAMP, default=_now)


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
