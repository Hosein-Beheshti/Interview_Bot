"""Structured job profile derived from free-text job context.

A user pastes anything they have about a role — title, company, the full job
description, a bullet list of requirements. One LLM call (in `llm.py`) turns that
into a `JobProfile`, which then drives both question generation and scoring.

This module owns the shape of that profile: the extraction tool schema, parsing
and validation of the model's output, graceful fallbacks for thin input, and the
formatting of the profile into a prompt-ready context block.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# Cap list lengths so a verbose extraction can't bloat every downstream prompt.
_MAX_SKILLS = 12
_MAX_FOCUS_AREAS = 8


@dataclass(frozen=True)
class JobProfile:
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


# Tool schema for the extraction call (forced tool use → guaranteed shape).
EXTRACT_TOOL = {
    "name": "submit_job_profile",
    "description": "Extract a structured interview profile from the job context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": "The job title being interviewed for, e.g. 'Senior Backend Engineer'.",
            },
            "company": {
                "type": "string",
                "description": "Company name if stated, otherwise omit.",
            },
            "seniority": {
                "type": "string",
                "description": "Seniority level if inferable, e.g. 'junior', 'mid', 'senior', 'staff'.",
            },
            "key_skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific skills, tools, or technologies the role requires and that questions should test.",
            },
            "focus_areas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Broader competency areas to probe, e.g. 'system design', 'team leadership'.",
            },
        },
        "required": ["role", "key_skills", "focus_areas"],
    },
}

EXTRACT_SYSTEM = (
    "You extract a concise, structured interview profile from whatever job "
    "information the user provides (title, company, description, requirements). "
    "Infer sensible values when details are implicit, but never invent a company "
    "name that isn't present. Use the submit_job_profile tool."
)


def minimal(role: str) -> JobProfile:
    """A profile carrying only a role — the graceful-degradation baseline."""
    return JobProfile(role=role)


def parse_profile(tool_input: dict, fallback_role: str) -> JobProfile:
    """Validate and normalize the extraction tool output into a JobProfile."""
    role = (tool_input.get("role") or "").strip() or fallback_role
    return JobProfile(
        role=role,
        company=_clean_optional(tool_input.get("company")),
        seniority=_clean_optional(tool_input.get("seniority")),
        key_skills=_clean_list(tool_input.get("key_skills"), _MAX_SKILLS),
        focus_areas=_clean_list(tool_input.get("focus_areas"), _MAX_FOCUS_AREAS),
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
