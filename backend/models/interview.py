from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    session_id = Column(String, primary_key=True, index=True)
    role = Column(String, nullable=False)
    messages = Column(JSON, default=list, nullable=False)
    answers_given = Column(Integer, default=0, nullable=False)
    is_complete = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    @property
    def question_number(self) -> int:
        return min(self.answers_given + 1, 5)
