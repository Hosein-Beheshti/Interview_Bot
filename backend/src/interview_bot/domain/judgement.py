"""Validation and parsing of the turn-quality judge's structured output."""
from __future__ import annotations

from dataclasses import dataclass, field

from .turn_quality import Criterion


@dataclass
class JudgeResult:
    criteria: dict[str, bool] = field(default_factory=dict)
    critique: str = ""


def parse_judgement(
    raw: dict, criteria: tuple[Criterion, ...]
) -> JudgeResult | None:
    """Validate the judge's structured output against the applicable criteria.

    Returns None if any applicable criterion key is missing or malformed, so
    callers can treat a broken judgement as "no judgement" rather than trusting
    bad data — mirrors `scoring.parse_score`'s strictness.
    """
    try:
        values = {c.key: bool(raw[c.key]) for c in criteria}
    except (KeyError, TypeError):
        return None
    return JudgeResult(criteria=values, critique=str(raw.get("critique", "")))
