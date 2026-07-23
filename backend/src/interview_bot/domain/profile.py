"""Structured job profile derived from free-text job context.

A user pastes anything they have about a role — title, company, the full job
description, a bullet list of requirements. `interview_bot.pipeline.session` turns that into
a `JobProfile`, which then drives both question generation and scoring.

This module owns the normalized profile type and its logic: parsing/validating
the model's output, graceful fallbacks for thin input, and formatting the profile
into a prompt-ready context block. It is pure of I/O. The extraction prompt and
its LLM I/O model live in `interview_bot.prompts.profile`; the extraction call in
`interview_bot.pipeline.profile`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .normalize import clean_optional, dedupe_capped

# Cap list lengths so a verbose extraction can't bloat every downstream prompt.
_MAX_SKILLS = 12
_MAX_FOCUS_AREAS = 8


@dataclass(frozen=True)
class JobProfile:
    """Normalized, immutable profile used throughout the interview domain."""

    role: str
    company: str | None = None
    seniority: str | None = None
    key_skills: tuple[str, ...] = field(default_factory=tuple)
    focus_areas: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key_skills"] = list(self.key_skills)
        data["focus_areas"] = list(self.focus_areas)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> JobProfile:
        return cls(
            role=data.get("role") or "",
            company=data.get("company"),
            seniority=data.get("seniority"),
            key_skills=tuple(data.get("key_skills") or ()),
            focus_areas=tuple(data.get("focus_areas") or ()),
        )


def minimal(role: str) -> JobProfile:
    """A profile carrying only a role — the graceful-degradation baseline."""
    return JobProfile(role=role)


def parse_profile(extracted: dict, fallback_role: str) -> JobProfile:
    """Validate and normalize the extracted profile into a JobProfile."""
    role = (extracted.get("role") or "").strip() or fallback_role
    return JobProfile(
        role=role,
        company=clean_optional(extracted.get("company")),
        seniority=clean_optional(extracted.get("seniority")),
        key_skills=dedupe_capped(extracted.get("key_skills"), _MAX_SKILLS),
        focus_areas=dedupe_capped(extracted.get("focus_areas"), _MAX_FOCUS_AREAS),
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
