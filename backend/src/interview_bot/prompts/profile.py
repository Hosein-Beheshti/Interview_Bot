"""Job-profile extraction: the system prompt and the LLM I/O contract.

Paired with `interview_bot.domain.profile` (the normalized domain type) and
`interview_bot.pipeline.profile` (the extraction call). The `ProfileExtraction`
shape and field descriptions are the model's structured-output contract — do not
rename the class or reword the fields casually: they are part of the assembled
request and changing them changes scoring/plan inputs.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileExtraction(BaseModel):
    """The shape the model fills when extracting a profile from job context.

    The LLM-I/O contract (one of three intentionally distinct profile shapes:
    this for extraction, `JobProfile` for the domain, `JobProfileSchema` for the
    API response). Delivered to the API as a structured-output format via
    `messages.parse`. Normalization (dedupe, caps, blank handling, fallback role)
    lives in `parse_profile`.
    """
    # NOTE: this class docstring is emitted verbatim as the JSON-schema
    # `description` in the assembled `llm.parse` request — it is part of the
    # frozen prompt bytes. Do not edit it without re-recording cassettes.

    role: str = Field(
        description="The job title being interviewed for, e.g. 'Senior Backend Engineer'."
    )
    company: str | None = Field(
        default=None, description="Company name if stated, otherwise null."
    )
    seniority: str | None = Field(
        default=None,
        description="Seniority level if inferable, e.g. 'junior', 'mid', 'senior', 'staff'.",
    )
    key_skills: list[str] = Field(
        default_factory=list,
        description="Specific skills, tools, or technologies the role requires and that questions should test.",
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description="Broader competency areas to probe, e.g. 'system design', 'team leadership'.",
    )


EXTRACT_SYSTEM = (
    "You extract a concise, structured interview profile from whatever job "
    "information the user provides (title, company, description, requirements). "
    "Infer sensible values when details are implicit, but never invent a company "
    "name that isn't present."
)
