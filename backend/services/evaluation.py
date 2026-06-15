"""Validation and parsing of the evaluator model's scoring output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from services import rubric as rubric_service
from services.rubric import MAX_SCORE, MIN_SCORE, Dimension


@dataclass
class ScoreData:
    overall: int
    dimensions: dict[str, int] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)


def parse_score(
    tool_input: dict,
    rubric: tuple[Dimension, ...] = rubric_service.DEFAULT_RUBRIC,
) -> Optional[ScoreData]:
    """Validate the submit_score tool output and compute the weighted overall.

    Returns None if any required dimension is missing or out of range, so callers
    can treat a malformed score as "no score" rather than trusting bad data.
    """
    try:
        raw_dimensions = tool_input["dimensions"]
        dimension_scores: dict[str, int] = {}
        for dimension in rubric:
            value = int(raw_dimensions[dimension.key])
            if not MIN_SCORE <= value <= MAX_SCORE:
                return None
            dimension_scores[dimension.key] = value
    except (KeyError, ValueError, TypeError):
        return None

    return ScoreData(
        overall=rubric_service.compute_overall(dimension_scores, rubric),
        dimensions=dimension_scores,
        strengths=[str(s) for s in tool_input.get("strengths", [])],
        improvements=[str(s) for s in tool_input.get("improvements", [])],
    )
