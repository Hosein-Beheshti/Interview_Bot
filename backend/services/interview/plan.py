"""The interview blueprint: an upfront, server-owned coverage plan.

At session creation we ask the model to lay out exactly one *slot* per main
question — each a specific skill to test, the intent behind it, and a difficulty
calibrated to seniority. The progression state machine then consumes one slot per
main question, which is what turns "ask some relevant questions" into a guaranteed
sweep of the role's key skills and focus areas.

The plan is pure data. Generation (the LLM call) lives in `services/session.py`;
consumption (rendering the slot into the turn instruction) lives in `prompt.py`.
This module owns only the shape, validation, and lookup — no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from . import job_profile
from .job_profile import JobProfile

# Reference key points per slot are capped so a verbose extraction can't bloat the
# scorer payload. 3-5 is the sweet spot for grading depth without over-constraining.
_MAX_KEY_POINTS = 6

# Allowed difficulty levels, easiest first. The model is asked for these; anything
# else is normalized to the middle rung.
DIFFICULTIES = ("foundational", "intermediate", "advanced")
_DEFAULT_DIFFICULTY = "intermediate"
_DIFFICULTY_SYNONYMS = {
    "easy": "foundational",
    "basic": "foundational",
    "beginner": "foundational",
    "medium": "intermediate",
    "moderate": "intermediate",
    "mid": "intermediate",
    "hard": "advanced",
    "difficult": "advanced",
    "expert": "advanced",
    "senior": "advanced",
}


@dataclass(frozen=True)
class PlanSlot:
    skill: str
    intent: str
    difficulty: str
    # What a strong answer to this question should cover. Generated with the plan
    # and fed to the scorer as a reference (reference-guided grading), never to the
    # interviewer — exposing them would let the question leak its own answer.
    key_points: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "intent": self.intent,
            "difficulty": self.difficulty,
            "key_points": list(self.key_points),
        }


@dataclass(frozen=True)
class InterviewPlan:
    slots: tuple[PlanSlot, ...]

    def slot_for(self, question_number: int) -> Optional[PlanSlot]:
        """The slot for a 1-based main-question number, or None if out of range."""
        index = question_number - 1
        if 0 <= index < len(self.slots):
            return self.slots[index]
        return None

    def to_dict(self) -> dict:
        return {"slots": [s.to_dict() for s in self.slots]}

    @classmethod
    def from_dict(cls, data: dict) -> "InterviewPlan":
        slots = tuple(
            PlanSlot(
                skill=s.get("skill", ""),
                intent=s.get("intent", ""),
                difficulty=s.get("difficulty", _DEFAULT_DIFFICULTY),
                key_points=tuple(s.get("key_points") or ()),
            )
            for s in (data.get("slots") or [])
        )
        return cls(slots=slots)


# ---------------------------------------------------------------------------
# LLM I/O contract (filled by the model at session creation)
# ---------------------------------------------------------------------------


class PlanSlotExtraction(BaseModel):
    skill: str = Field(
        description="The specific skill or topic this question tests, e.g. 'Kubernetes networking'."
    )
    intent: str = Field(
        description="What the question should assess about that skill — the angle to probe."
    )
    difficulty: str = Field(
        description="One of: foundational, intermediate, advanced — calibrated to the role's seniority."
    )
    key_points: list[str] = Field(
        default_factory=list,
        description=(
            "3-5 specific things a strong answer should cover: the core concepts, "
            "tradeoffs, edge cases, or facts that distinguish real depth from a "
            "surface-level reply. Each a short phrase. Used later to grade answers, "
            "so be concrete and answer-focused, not a restatement of the question."
        ),
    )


class PlanExtraction(BaseModel):
    slots: list[PlanSlotExtraction] = Field(
        default_factory=list,
        description="One slot per main question, ordered, giving non-overlapping coverage of the role.",
    )


EXTRACT_SYSTEM = (
    "You design a structured interview blueprint. Given a job profile and a target "
    "number of main questions, produce exactly that many question slots that "
    "together give broad, non-overlapping coverage of the role's most important "
    "skills and focus areas. Order them to flow naturally — foundational topics "
    "before advanced ones. Calibrate each difficulty to the stated seniority. Each "
    "slot names the specific skill to test, the intent (what to assess), a "
    "difficulty, and the key points a strong answer should cover — the concepts, "
    "tradeoffs, and edge cases later used to grade the candidate's answer."
)


def build_extraction_messages(profile: JobProfile, num_questions: int) -> list[dict]:
    return [
        {
            "role": "user",
            "content": (
                f"{job_profile.build_context(profile)}\n\n"
                f"Design exactly {num_questions} interview question slots for this role."
            ),
        }
    ]


# ---------------------------------------------------------------------------
# Validation / normalization
# ---------------------------------------------------------------------------


def parse_plan(extracted: dict, profile: JobProfile, num_questions: int) -> InterviewPlan:
    """Normalize the model's slots into exactly `num_questions` valid slots.

    The model is asked for the right count, but we never trust it blindly: extra
    slots are truncated and a shortfall is padded from the profile's own skills
    (then the role), so the plan always lines up 1:1 with the main questions.
    """
    slots: list[PlanSlot] = []
    for item in extracted.get("slots") or []:
        skill = str(item.get("skill", "")).strip()
        intent = str(item.get("intent", "")).strip()
        if not skill and not intent:
            continue
        slots.append(
            PlanSlot(
                skill=skill or intent,
                intent=intent or skill,
                difficulty=_normalize_difficulty(item.get("difficulty")),
                key_points=_clean_points(item.get("key_points")),
            )
        )

    slots = slots[:num_questions]
    if len(slots) < num_questions:
        slots = _pad(slots, num_questions, profile)
    return InterviewPlan(slots=tuple(slots))


def resolve(session) -> Optional[InterviewPlan]:
    """Reconstruct a session's plan from its stored JSON, or None if unplanned."""
    data = getattr(session, "interview_plan", None)
    if not data:
        return None
    return InterviewPlan.from_dict(data)


def _clean_points(value, limit: int = _MAX_KEY_POINTS) -> tuple[str, ...]:
    """Trim, drop blanks, dedupe case-insensitively, and cap the reference points."""
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


def _normalize_difficulty(value) -> str:
    if not isinstance(value, str):
        return _DEFAULT_DIFFICULTY
    cleaned = value.strip().lower()
    if cleaned in DIFFICULTIES:
        return cleaned
    return _DIFFICULTY_SYNONYMS.get(cleaned, _DEFAULT_DIFFICULTY)


def _pad(slots: list[PlanSlot], num_questions: int, profile: JobProfile) -> list[PlanSlot]:
    """Top up a short plan with the profile's uncovered skills, then the role."""
    covered = {s.skill.lower() for s in slots}
    pool = [*profile.key_skills, *profile.focus_areas]
    extras = [s for s in pool if s.lower() not in covered]

    next_extra = 0
    while len(slots) < num_questions:
        if next_extra < len(extras):
            skill = extras[next_extra]
            next_extra += 1
        else:
            skill = profile.role
        slots.append(
            PlanSlot(
                skill=skill,
                intent=f"Assess the candidate's depth in {skill}.",
                difficulty=_DEFAULT_DIFFICULTY,
            )
        )
    return slots
