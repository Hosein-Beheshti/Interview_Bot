"""CV-context policy for the interviewer.

Decides how the candidate's CV reaches the model each turn: short CVs go in full
(best grounding, cached prefix makes it nearly free); long CVs fall back to
per-question vector retrieval (`rag`). The mechanics of chunking/embedding/search
live in `rag`; this module owns only the full-text-vs-retrieval policy.
"""
from __future__ import annotations

from interview_bot.config import settings
from interview_bot.logger import logger

from . import rag


async def build_cv_context(session) -> str:
    """Return CV context for the next question, or '' when no CV is indexed.

    Never raises — retrieval failures degrade to no context.
    """
    if not session.has_cv:
        return ""

    full_text = session.cv_full_text
    if full_text and len(full_text) <= settings.cv_full_text_max_chars:
        return f"Full CV of the candidate:\n{full_text}"

    # Long CV: retrieve the slice relevant to the topic in play. The last question
    # is the deliberate statement of that topic; on the opening turn there is no
    # question yet, so seed the query with the role.
    last_question = next(
        (m["content"] for m in reversed(session.messages) if m["role"] == "assistant"),
        "",
    )
    query = last_question or session.role
    if not query:
        return ""

    try:
        return await rag.retrieve(session.session_id, query)
    except Exception as e:
        logger.warning(f"CV retrieval failed | session={session.session_id} | error={e}")
        return ""
