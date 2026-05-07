import json
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ScoreData:
    score: int
    strengths: list[str]
    improvements: list[str]


def extract_score_json(reply: str) -> Optional[ScoreData]:
    """Extract JSON score data from Claude's response.

    Tries multiple patterns to handle minor JSON variations from the LLM.
    """
    json_str = _find_json_block(reply)
    if not json_str:
        return None

    try:
        data = json.loads(json_str)
        score = int(data.get("score", 0))
        if not 1 <= score <= 10:
            return None

        return ScoreData(
            score=score,
            strengths=_ensure_list(data.get("strengths")),
            improvements=_ensure_list(data.get("improvements")),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def is_interview_complete(reply: str) -> bool:
    return "INTERVIEW_COMPLETE" in reply


def _find_json_block(text: str) -> Optional[str]:
    match = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
    return match.group(0) if match else None


def _ensure_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []
