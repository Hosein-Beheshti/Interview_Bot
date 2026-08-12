"""CV-context policy for the interviewer.

Decides how the candidate's CV reaches the model each turn: short CVs go in full
(best grounding, cached prefix makes it nearly free); long CVs fall back to
per-question vector retrieval (`rag`). The mechanics of chunking/embedding/search
live in `rag`; this module owns only the full-text-vs-retrieval policy.

The two paths differ in more than size, which is why `CVContext` carries a
`stable` flag: full text is identical on every turn of a session and belongs in
the cached prompt prefix, while retrieved excerpts change with every question and
must not be — marking volatile text as cacheable writes a fresh cache entry per
turn, which costs more than not caching at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from interview_bot.config import settings
from interview_bot.logger import logger

from . import rag


@dataclass(frozen=True)
class CVContext:
    """CV text for one turn, plus whether it is turn-invariant."""

    text: str
    stable: bool

    def __bool__(self) -> bool:
        return bool(self.text)


# No CV, or retrieval degraded to nothing. Trivially stable.
EMPTY = CVContext(text="", stable=True)


async def build_cv_context(session, topic: str | None = None) -> CVContext:
    """Return CV context for the next question, or `EMPTY` when none is indexed.

    `topic` is what the turn about to be generated will ask about — the planned
    slot for a main question, the current topic for a follow-up. It is the
    retrieval query: a main question moves to a NEW topic, so querying with the
    question just asked would retrieve the slice of the CV being left behind.
    Falls back to the role when the caller has no topic (an unplanned opening
    turn, where nothing more specific is known yet).

    Never raises — retrieval failures degrade to no context.
    """
    if not session.has_cv:
        return EMPTY

    full_text = session.cv_full_text
    if full_text and len(full_text) <= settings.cv_full_text_max_chars:
        return CVContext(text=f"Full CV of the candidate:\n{full_text}", stable=True)

    query = topic or session.role
    if not query:
        return EMPTY

    try:
        retrieved = await rag.retrieve(session.session_id, query)
    except Exception as e:
        logger.warning(f"CV retrieval failed | session={session.session_id} | error={e}")
        return EMPTY

    return CVContext(text=retrieved, stable=False) if retrieved else EMPTY
