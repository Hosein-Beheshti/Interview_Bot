"""Evaluation rubric — the criteria a candidate's answer is scored against.

The rubric is a single, data-driven source of truth. Everything else is derived
from it: the structured-output score format, the rubric description handed to the
evaluator model, and the weighted overall score. Adding, removing, or reweighting
a dimension is a one-line change here — no other file needs to be touched.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

# Score bounds for every dimension. Centralized so the schema, validation, and
# prompt all agree.
#
# The floor is 0, not 1, because an unanswered question already scores 0: a
# `no_answer` forces the overall to zero (see `domain.scoring.parse_score`), and
# a floor of 1 put that value outside the scale it was averaged into. Zero now
# means what it is used for — nothing to assess — rather than acting as an
# out-of-band sentinel.
MIN_SCORE = 0
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


def _rubric_version(rubric: tuple[Dimension, ...]) -> str:
    """Short content hash of the rubric definition (keys, labels, text, weights).

    Changes automatically whenever a dimension is added, removed, reworded, or
    reweighted — so a scoring result can always be traced to the exact rubric
    that produced it, and results across rubric versions are never silently
    compared. See `interview_bot.prompts.scoring.PROMPT_VERSION` for the prompt.
    """
    material = "|".join(
        f"{d.key}:{d.label}:{d.description}:{d.weight}" for d in rubric
    ) + f"|{MIN_SCORE}-{MAX_SCORE}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


RUBRIC_VERSION = _rubric_version(DEFAULT_RUBRIC)


def build_score_format(rubric: tuple[Dimension, ...] = DEFAULT_RUBRIC) -> dict:
    """Build the structured-output `format` for scoring, derived from the rubric.

    Scoring is a single-shot structured generation, not an action — so the schema
    is delivered via `output_config.format` (JSON-schema structured outputs), not
    as a forced tool. The API constrains generation to this exact shape: every
    dimension present, every score a valid integer in range. Structured outputs do
    not honor numeric `minimum`/`maximum`, so the score range is expressed as an
    `enum` of the allowed integers (which is enforced). All objects set
    `additionalProperties: false`, as structured outputs require.
    """
    allowed_scores = list(range(MIN_SCORE, MAX_SCORE + 1))
    dimension_props = {
        d.key: {
            "type": "integer",
            "enum": allowed_scores,
            "description": d.description,
        }
        for d in rubric
    }
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "critique": {
                    "type": "string",
                    "description": (
                        "Required first step — write this before assigning any scores. "
                        "In 1-2 sentences, identify the specific gaps, errors, or "
                        "missing depth: name the exact concepts, tradeoffs, or edge "
                        "cases that are absent or wrong. If strong, state what is "
                        "missing for 9-10. Keep it under 40 words. "
                        "Scores must follow from this critique: significant gaps → "
                        "below 7; only minor gaps → not above 8."
                    ),
                },
                "dimensions": {
                    "type": "object",
                    "additionalProperties": False,
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
                "answer_type": {
                    "type": "string",
                    "enum": ["substantive", "partial", "no_answer"],
                    "description": (
                        "Classify by how COMPLETE the attempt is, not how correct: "
                        "'substantive' = a complete attempt that engages with the "
                        "question (a confident but wrong answer is still "
                        "substantive); 'partial' = a real but incomplete attempt "
                        "(trails off, bare definition, single word); 'no_answer' = "
                        "no usable content for this question (don't-know, skip, "
                        "empty, or entirely off-topic)."
                    ),
                },
                "follow_up_recommended": {
                    "type": "boolean",
                    "description": (
                        "True if a single follow-up on the SAME topic would "
                        "meaningfully reveal more about the candidate's depth — "
                        "e.g. the answer was promising but shallow, or made a "
                        "claim worth probing. False if the topic is sufficiently "
                        "covered and the interview should move to a new question."
                    ),
                },
            },
            "required": [
                "critique",
                "dimensions",
                "strengths",
                "improvements",
                "answer_type",
                "follow_up_recommended",
            ],
        },
    }


def describe_rubric(rubric: tuple[Dimension, ...] = DEFAULT_RUBRIC) -> str:
    """Human-readable rubric block for the evaluator's system prompt."""
    lines = [
        f"Score each dimension from {MIN_SCORE} (nothing to assess) to {MAX_SCORE} "
        "(excellent). Calibrate against the whole scale and reserve the top band:",
        "- 0: no usable content for this question - nothing to assess on this dimension.",
        "- 1-3: incorrect, irrelevant, or barely addresses the dimension.",
        "- 4-6: partially correct or shallow - the basic idea with little depth. A "
        "textbook definition, or a correct answer that names no tradeoffs, edge cases, "
        "or failure modes, belongs here even when it is fluent and confident.",
        "- 7-8: correct and solid, and names at least one concrete tradeoff, edge case, "
        "or failure mode - but not several, or not precisely.",
        "- 9-10: comprehensive and precise - covers several tradeoffs, edge cases, or "
        "failure modes specific to the question asked.",
        "",
        "Dimensions:",
    ]
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
