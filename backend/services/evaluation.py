from dataclasses import dataclass
from typing import Optional


@dataclass
class ScoreData:
    score: int
    strengths: list[str]
    improvements: list[str]


def parse_score(tool_input: dict) -> Optional[ScoreData]:
    """Validate and parse the output of the submit_score tool call."""
    try:
        score = int(tool_input["score"])
        if not 1 <= score <= 10:
            return None
        return ScoreData(
            score=score,
            strengths=[str(s) for s in tool_input.get("strengths", [])],
            improvements=[str(s) for s in tool_input.get("improvements", [])],
        )
    except (KeyError, ValueError, TypeError):
        return None


def is_interview_complete(reply: str) -> bool:
    return "INTERVIEW_COMPLETE" in reply
