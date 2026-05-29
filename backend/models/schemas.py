from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    role: str = "Software Engineer"


class ScoreResult(BaseModel):
    score: int
    strengths: list[str]
    improvements: list[str]


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    question_number: int
    is_complete: bool
    score: Optional[ScoreResult] = None


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
