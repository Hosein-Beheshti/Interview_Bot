"""Validation and parsing of the evaluator model's scoring output."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import rubric as rubric_service
from .rubric import MAX_SCORE, MIN_SCORE, Dimension

# Allowed values for ScoreData.answer_type; anything else falls back to the first.
ANSWER_TYPES = ("substantive", "partial", "no_answer")


@dataclass
class ScoreData:
    overall: int
    dimensions: dict[str, int] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    # Control signals that drive interview progression (see pipeline/interview.py).
    answer_type: str = "substantive"
    follow_up_recommended: bool = False
    # Evaluator chain-of-thought: written before scores to anchor calibration.
    # Never shown to the candidate; used for observability and eval analysis.
    critique: str = ""


def parse_score(
    raw: dict,
    rubric: tuple[Dimension, ...] = rubric_service.DEFAULT_RUBRIC,
) -> ScoreData | None:
    """Validate the structured score output and compute the weighted overall.

    Returns None if any required dimension is missing or out of range, so callers
    can treat a malformed score as "no score" rather than trusting bad data.
    """
    try:
        raw_dimensions = raw["dimensions"]
        dimension_scores: dict[str, int] = {}
        for dimension in rubric:
            value = int(raw_dimensions[dimension.key])
            if not MIN_SCORE <= value <= MAX_SCORE:
                return None
            dimension_scores[dimension.key] = value
    except (KeyError, ValueError, TypeError):
        return None

    answer_type = raw.get("answer_type", "substantive")
    if answer_type not in ANSWER_TYPES:
        answer_type = "substantive"

    strengths = [str(s) for s in raw.get("strengths", [])]
    improvements = [str(s) for s in raw.get("improvements", [])]
    critique = str(raw.get("critique", ""))

    # A non-answer earns no credit: force the overall to 0 and drop strengths,
    # regardless of how the model scored the individual dimensions. 0 is the
    # bottom of the rubric scale (see `rubric.MIN_SCORE`), so this stays a real
    # score rather than a sentinel sitting below the range it is averaged into.
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
        follow_up_recommended=bool(raw.get("follow_up_recommended", False)),
        critique=critique,
    )
