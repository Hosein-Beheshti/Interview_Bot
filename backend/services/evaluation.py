"""Validation and parsing of the evaluator model's scoring output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from services import rubric as rubric_service
from services.rubric import MAX_SCORE, MIN_SCORE, Dimension


# Allowed values for ScoreData.answer_type; anything else falls back to the first.
ANSWER_TYPES = ("substantive", "partial", "no_answer")


@dataclass
class ScoreData:
    overall: int
    dimensions: dict[str, int] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    # Control signals that drive interview progression (see routes/chat.py).
    answer_type: str = "substantive"
    follow_up_recommended: bool = False


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

    answer_type = tool_input.get("answer_type", "substantive")
    if answer_type not in ANSWER_TYPES:
        answer_type = "substantive"

    strengths = [str(s) for s in tool_input.get("strengths", [])]
    improvements = [str(s) for s in tool_input.get("improvements", [])]

    # A non-answer earns no credit: force the overall to 0 and drop strengths,
    # regardless of how the model scored the individual dimensions.
    if answer_type == "no_answer":
        overall = 0
        strengths = []
        dimension_scores = {key: 0 for key in dimension_scores}
    else:
        overall = rubric_service.compute_overall(dimension_scores, rubric)

    return ScoreData(
        overall=overall,
        dimensions=dimension_scores,
        strengths=strengths,
        improvements=improvements,
        answer_type=answer_type,
        follow_up_recommended=bool(tool_input.get("follow_up_recommended", False)),
    )
