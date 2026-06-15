"""Evaluation rubric — the criteria a candidate's answer is scored against.

The rubric is a single, data-driven source of truth. Everything else is derived
from it: the scoring tool's JSON schema, the rubric description handed to the
evaluator model, and the weighted overall score. Adding, removing, or reweighting
a dimension is a one-line change here — no other file needs to be touched.
"""
from __future__ import annotations

from dataclasses import dataclass

# Score bounds for every dimension. Centralized so the schema, validation, and
# prompt all agree.
MIN_SCORE = 1
MAX_SCORE = 10


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    description: str
    weight: float = 1.0


# Default rubric. Each dimension is intentionally role-agnostic in name but
# role-aware in scoring: the evaluator is given the job profile, so "Technical
# Relevance" is judged against the specific role's requirements.
DEFAULT_RUBRIC: tuple[Dimension, ...] = (
    Dimension(
        key="technical_relevance",
        label="Technical Relevance",
        description=(
            "How directly the answer addresses the specific skill or topic being "
            "tested, relative to the target role's requirements."
        ),
    ),
    Dimension(
        key="depth_accuracy",
        label="Depth & Accuracy",
        description=(
            "Technical correctness and substance. Distinguishes genuine, deep "
            "understanding from surface-level, vague, or hand-wavy answers."
        ),
    ),
    Dimension(
        key="communication",
        label="Communication",
        description="Clarity, structure, and conciseness of the explanation.",
    ),
)


def build_score_tool_schema(rubric: tuple[Dimension, ...] = DEFAULT_RUBRIC) -> dict:
    """Build the Anthropic tool schema for scoring directly from the rubric."""
    dimension_props = {
        d.key: {
            "type": "integer",
            "minimum": MIN_SCORE,
            "maximum": MAX_SCORE,
            "description": d.description,
        }
        for d in rubric
    }
    return {
        "name": "submit_score",
        "description": "Score the candidate's answer on every rubric dimension.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "object",
                    "properties": dimension_props,
                    "required": [d.key for d in rubric],
                },
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1-3 concrete strengths of the answer.",
                },
                "improvements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1-3 concrete, actionable areas to improve.",
                },
            },
            "required": ["dimensions", "strengths", "improvements"],
        },
    }


def describe_rubric(rubric: tuple[Dimension, ...] = DEFAULT_RUBRIC) -> str:
    """Human-readable rubric block for the evaluator's system prompt."""
    lines = [f"Score each dimension from {MIN_SCORE} (poor) to {MAX_SCORE} (excellent):"]
    lines.extend(f"- {d.label}: {d.description}" for d in rubric)
    return "\n".join(lines)


def compute_overall(
    dimension_scores: dict[str, int], rubric: tuple[Dimension, ...] = DEFAULT_RUBRIC
) -> int:
    """Weighted average of dimension scores, rounded to the nearest integer."""
    total_weight = sum(d.weight for d in rubric if d.key in dimension_scores)
    if total_weight == 0:
        return 0
    weighted = sum(
        dimension_scores[d.key] * d.weight for d in rubric if d.key in dimension_scores
    )
    return round(weighted / total_weight)


def labelled(
    dimension_scores: dict[str, int], rubric: tuple[Dimension, ...] = DEFAULT_RUBRIC
) -> list[tuple[str, str, int]]:
    """Pair each dimension score with its display label, in rubric order."""
    return [
        (d.key, d.label, dimension_scores[d.key])
        for d in rubric
        if d.key in dimension_scores
    ]
