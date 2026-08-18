"""HTTP request/response DTOs — the API wire contract.

Deliberately separate from the domain types (`domain.profile.JobProfile`, …) and
the LLM extraction models (`prompts.*`): each boundary owns its own shape so the
wire format can evolve independently of the internals.
"""
from pydantic import BaseModel, Field

from interview_bot.config import settings

# The candidate picks how many main questions the interview asks. `max_questions`
# is both the ceiling and the value used when the field is omitted, so leaving it
# out keeps the previous behaviour of a full-length interview.
MAX_QUESTIONS = settings.max_questions
JOB_CONTEXT_MAX_CHARS = settings.job_context_max_chars
CHAT_MESSAGE_MAX_CHARS = settings.chat_message_max_chars
ROLE_MAX_CHARS = settings.role_max_chars


class JobProfileSchema(BaseModel):
    role: str
    company: str | None = None
    seniority: str | None = None
    key_skills: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    job_context: str = Field(..., min_length=1, max_length=JOB_CONTEXT_MAX_CHARS)
    num_questions: int = Field(default=MAX_QUESTIONS, ge=1, le=MAX_QUESTIONS)


class PlanSlotSchema(BaseModel):
    skill: str
    intent: str
    difficulty: str


class SessionCreateResponse(BaseModel):
    session_id: str
    role: str
    num_questions: int
    job_profile: JobProfileSchema
    # The interview blueprint shown to the candidate up front. Empty if planning
    # was skipped or failed (the interviewer then self-selects topics).
    plan: list[PlanSlotSchema] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=CHAT_MESSAGE_MAX_CHARS)
    session_id: str | None = None
    # Optional: only used when no session_id is supplied (lazy session creation).
    role: str | None = Field(default=None, min_length=1, max_length=ROLE_MAX_CHARS)
    num_questions: int | None = Field(default=None, ge=1, le=MAX_QUESTIONS)
    job_context: str | None = Field(default=None, min_length=1, max_length=JOB_CONTEXT_MAX_CHARS)


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
    # Graded answers only — `overall` and `breakdown` never include an answer the
    # evaluator failed to grade.
    breakdown: list[QuestionScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    # How many answers could not be evaluated. Non-zero means `overall` covers
    # only part of the interview; `copy_text` already says so in words.
    unscored: int = 0
    copy_text: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    status: str
    question_number: int
    num_questions: int
    is_complete: bool
    score: ScoreResult | None = None
    # Turn type of `reply`: "main_question" | "follow_up" | "closing".
    # Lets the UI distinguish a numbered question from a follow-up.
    mode: str | None = None
    # Populated once the interview completes; null otherwise.
    summary: InterviewSummary | None = None


class CVUploadResponse(BaseModel):
    session_id: str
    filename: str
    chunk_count: int
    sections: list[str]


class CVStatusResponse(BaseModel):
    session_id: str
    has_cv: bool
    filename: str | None = None
    sections: list[str] | None = None


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    picture_url: str | None = None
    credits: int
