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
    is_complete = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    cv_filename = Column(String, nullable=True)
    cv_indexed_at = Column(DateTime, nullable=True)
    cv_sections = Column(JSON, nullable=True)
    cv_full_text = Column(Text, nullable=True)

    @property
    def has_cv(self) -> bool:
        return self.cv_indexed_at is not None

    @property
    def question_number(self) -> int:
        return min(self.answers_given + 1, self.num_questions)


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
