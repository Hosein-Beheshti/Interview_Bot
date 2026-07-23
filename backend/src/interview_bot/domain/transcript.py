"""Pure queries over the interview transcript (the role/content message list)."""
from __future__ import annotations


def last_assistant(messages: list[dict]) -> str | None:
    """The content of the most recent assistant (interviewer) message, or None.

    This is the question currently in play — used to anchor a follow-up, to grade
    the answer against, and to seed CV retrieval.
    """
    return next(
        (m["content"] for m in reversed(messages) if m["role"] == "assistant"),
        None,
    )
