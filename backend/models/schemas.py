from pydantic import BaseModel, Field
from typing import Optional


class JobProfileSchema(BaseModel):
    role: str
    company: Optional[str] = None
    seniority: Optional[str] = None
    key_skills: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    job_context: str = Field(..., min_length=1, max_length=8000)
    num_questions: int = Field(default=5, ge=1, le=20)


class SessionCreateResponse(BaseModel):
    session_id: str
    role: str
    num_questions: int
    job_profile: JobProfileSchema


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    # Optional: only used when no session_id is supplied (lazy session creation).
    role: Optional[str] = Field(default=None, min_length=1, max_length=100)
    num_questions: Optional[int] = Field(default=None, ge=1, le=20)
    job_context: Optional[str] = Field(default=None, min_length=1, max_length=8000)


class DimensionScore(BaseModel):
    key: str
    label: str
    score: int


class ScoreResult(BaseModel):
    score: int  # overall weighted-average score across the rubric dimensions
    dimensions: list[DimensionScore] = Field(default_factory=list)
    strengths: list[str]
    improvements: list[str]


class QuestionScore(BaseModel):
    label: str  # e.g. "Q1" or "Q2 follow-up"
    score: int


class InterviewSummary(BaseModel):
    """Server-computed interview result. The client renders this verbatim."""
    role: str
    overall: float
    breakdown: list[QuestionScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    copy_text: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    status: str
    question_number: int
    num_questions: int
    is_complete: bool
    score: Optional[ScoreResult] = None
    # Turn type of `reply`: "main_question" | "follow_up" | "closing".
    # Lets the UI distinguish a numbered question from a follow-up.
    mode: Optional[str] = None
    # Populated once the interview completes; null otherwise.
    summary: Optional[InterviewSummary] = None


class CVUploadResponse(BaseModel):
    session_id: str
    filename: str
    chunk_count: int
    sections: list[str]


class CVStatusResponse(BaseModel):
    session_id: str
    has_cv: bool
    filename: Optional[str] = None
    sections: Optional[list[str]] = None
