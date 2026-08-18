"""Client-facing configuration — the limits the browser has to agree with.

The UI needs the same numbers the API enforces. A textarea that lets someone type
past `chat_message_max_chars` turns a server 422 into a surprise after they have
written the answer; a question picker offering more than `max_questions` offers a
choice that cannot be made. Those numbers live in `config.Settings`, and this
endpoint publishes the subset the UI needs so the client never keeps its own copy.

Two rules for what belongs here:

  * Only limits the server actually enforces. A value published here that nothing
    checks is a claim, not a limit — and the client would present it as real.
  * Nothing secret. This is unauthenticated: the browser needs it before login,
    and every value in it is already discoverable by probing the endpoints it
    describes.

Client-side checks derived from this are a courtesy, not enforcement — the server
re-validates everything regardless.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from interview_bot.config import settings
from interview_bot.integrations import cv_parser

router = APIRouter(tags=["meta"])


class ClientConfig(BaseModel):
    """Server-owned limits the client mirrors. Field names match their settings."""

    max_questions: int
    role_max_chars: int
    job_context_max_chars: int
    chat_message_max_chars: int
    cv_max_bytes: int
    cv_min_chars: int
    # Accepted upload extensions, dotted and lowercase (".pdf"). Sorted so the
    # response is stable — an unordered set would make the payload vary per
    # process and defeat any caching in front of it.
    cv_accepted_extensions: list[str] = Field(default_factory=list)


@router.get("/config", response_model=ClientConfig)
async def client_config() -> ClientConfig:
    return ClientConfig(
        max_questions=settings.max_questions,
        role_max_chars=settings.role_max_chars,
        job_context_max_chars=settings.job_context_max_chars,
        chat_message_max_chars=settings.chat_message_max_chars,
        cv_max_bytes=settings.cv_max_bytes,
        cv_min_chars=settings.cv_min_chars,
        cv_accepted_extensions=sorted(cv_parser.SUPPORTED_EXTENSIONS),
    )
