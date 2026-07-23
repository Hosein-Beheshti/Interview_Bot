"""Interview-plan extraction: the system prompt, the LLM I/O contract, and the
message builder.

Paired with `interview_bot.domain.plan` (the normalized blueprint type + lookup)
and `interview_bot.pipeline.plan` (the extraction call). The `PlanExtraction` /
`PlanSlotExtraction` shapes and the prompt text are the model's structured-output
contract — part of the assembled request, so don't rename or reword casually.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from interview_bot.domain.profile import JobProfile, build_context


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
                f"{build_context(profile)}\n\n"
                f"Design exactly {num_questions} interview question slots for this role."
            ),
        }
    ]
