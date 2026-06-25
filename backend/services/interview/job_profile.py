"""Structured job profile derived from free-text job context.

A user pastes anything they have about a role — title, company, the full job
description, a bullet list of requirements. `services/session.py` turns that into
a `JobProfile`, which then drives both question generation and scoring.

This module owns the shape of that profile: the extraction schema, parsing and
validation of the model's output, graceful fallbacks for thin input, and the
formatting of the profile into a prompt-ready context block. It is pure of I/O.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

# Cap list lengths so a verbose extraction can't bloat every downstream prompt.
_MAX_SKILLS = 12
_MAX_FOCUS_AREAS = 8


@dataclass(frozen=True)
class JobProfile:
    """Normalized, immutable profile used throughout the interview domain."""

    role: str
    company: Optional[str] = None
    seniority: Optional[str] = None
    key_skills: tuple[str, ...] = field(default_factory=tuple)
    focus_areas: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key_skills"] = list(self.key_skills)
        data["focus_areas"] = list(self.focus_areas)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "JobProfile":
        return cls(
            role=data.get("role") or "",
            company=data.get("company"),
            seniority=data.get("seniority"),
            key_skills=tuple(data.get("key_skills") or ()),
            focus_areas=tuple(data.get("focus_areas") or ()),
        )


class ProfileExtraction(BaseModel):
    """The shape the model fills when extracting a profile from job context.

    The LLM-I/O contract (one of three intentionally distinct profile shapes:
    this for extraction, `JobProfile` for the domain, `JobProfileSchema` for the
    API response). Delivered to the API as a structured-output format via
    `messages.parse`. Normalization (dedupe, caps, blank handling, fallback role)
    lives in `parse_profile`.
    """

    role: str = Field(
        description="The job title being interviewed for, e.g. 'Senior Backend Engineer'."
    )
    company: Optional[str] = Field(
        default=None, description="Company name if stated, otherwise null."
    )
    seniority: Optional[str] = Field(
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


def minimal(role: str) -> JobProfile:
    """A profile carrying only a role — the graceful-degradation baseline."""
    return JobProfile(role=role)


def parse_profile(extracted: dict, fallback_role: str) -> JobProfile:
    """Validate and normalize the extracted profile into a JobProfile."""
    role = (extracted.get("role") or "").strip() or fallback_role
    return JobProfile(
        role=role,
        company=_clean_optional(extracted.get("company")),
        seniority=_clean_optional(extracted.get("seniority")),
        key_skills=_clean_list(extracted.get("key_skills"), _MAX_SKILLS),
        focus_areas=_clean_list(extracted.get("focus_areas"), _MAX_FOCUS_AREAS),
    )


def build_context(profile: JobProfile) -> str:
    """Render the profile as a prompt-ready context block."""
    lines = ["Job context:"]
    if profile.company:
        lines.append(f"- Company: {profile.company}")
    lines.append(f"- Target role: {profile.role}")
    if profile.seniority:
        lines.append(f"- Seniority: {profile.seniority}")
    if profile.key_skills:
        lines.append(f"- Key skills to assess: {', '.join(profile.key_skills)}")
    if profile.focus_areas:
        lines.append(f"- Focus areas: {', '.join(profile.focus_areas)}")
    return "\n".join(lines)


def _clean_optional(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_list(value, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text.lower() not in (s.lower() for s in seen):
            seen.append(text)
        if len(seen) >= limit:
            break
    return tuple(seen)
