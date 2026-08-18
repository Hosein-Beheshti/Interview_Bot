"""Retrieval-Augmented Generation for CV-aware interviewing.

Pipeline:
    parse_cv -> chunk -> embed -> upsert into pgvector (scoped by session_id)

At query time:
    embed(query) -> top-k cosine search -> formatted context block for the LLM
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from interview_bot.config import settings
from interview_bot.integrations import embeddings
from interview_bot.integrations.cv_parser import ParsedCV
from interview_bot.logger import logger
from interview_bot.persistence import vector_store
from interview_bot.persistence.vector_store import RetrievedChunk

# Section headers commonly found in CVs. Matched case-insensitively at line start.
_SECTION_HEADERS = (
    "experience", "work experience", "professional experience", "employment",
    "education", "academic", "qualifications",
    "skills", "technical skills", "core competencies",
    "projects", "personal projects", "open source",
    "certifications", "awards", "publications",
    "summary", "profile", "objective", "about",
    "languages", "interests",
)

_SECTION_PATTERN = re.compile(
    r"^\s*(" + "|".join(_SECTION_HEADERS) + r")\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

@dataclass(frozen=True)
class TextChunk:
    """A pre-embedding slice of CV text, tagged by the section it came from."""

    text: str
    section: str


@dataclass(frozen=True)
class IndexResult:
    chunk_count: int
    sections: list[str]


async def index_cv(session_id: str, cv: ParsedCV) -> IndexResult:
    """Chunk a parsed CV, embed each chunk, and persist to the vector store."""
    chunks = chunk_cv(cv.text)
    if not chunks:
        raise ValueError("CV produced no chunks")

    vectors = await embeddings.embed([c.text for c in chunks], input_type="document")

    vector_store.upsert(
        session_id=session_id,
        chunks=[c.text for c in chunks],
        embeddings=vectors,
        sections=[c.section for c in chunks],
    )

    sections = sorted({c.section for c in chunks if c.section})
    logger.info(
        f"CV indexed | session={session_id} | chunks={len(chunks)} | sections={sections}"
    )
    return IndexResult(chunk_count=len(chunks), sections=sections)


async def retrieve(session_id: str, query: str, top_k: int | None = None) -> str:
    """Return formatted CV context for a query, or empty string if none indexed."""
    k = top_k or settings.rag_top_k
    query_vec = (await embeddings.embed([query], input_type="query"))[0]

    chunks = vector_store.query(session_id, query_vec, top_k=k)
    if not chunks:
        return ""

    return _format_context(chunks)


def delete_index(session_id: str) -> None:
    vector_store.delete_session(session_id)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_cv(text: str) -> list[TextChunk]:
    """Split a CV into semantically coherent chunks tagged by section."""
    sections = _split_sections(text)
    chunks: list[TextChunk] = []
    for section_name, body in sections:
        for piece in _split_long_text(body):
            chunks.append(TextChunk(text=piece, section=section_name))
    return chunks


def _split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(_SECTION_PATTERN.finditer(text))
    if not matches:
        return [("general", text)]

    sections: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("header", preamble))

    for i, m in enumerate(matches):
        name = m.group(1).lower()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((name, body))
    return sections


def _split_long_text(text: str) -> list[str]:
    """Sliding-window split with paragraph-aware boundaries."""
    target = settings.chunk_target_chars
    if len(text) <= target:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= target:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) <= target:
                current = para
            else:
                chunks.extend(_window_split(para))
                current = ""

    if current:
        chunks.append(current)
    return chunks


def _window_split(text: str) -> list[str]:
    target = settings.chunk_target_chars
    step = target - settings.chunk_overlap_chars
    return [text[i : i + target] for i in range(0, len(text), step)]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_context(chunks: list[RetrievedChunk]) -> str:
    lines = ["Relevant excerpts from the candidate's CV:"]
    for i, chunk in enumerate(chunks, start=1):
        label = chunk.section.title() if chunk.section else "Excerpt"
        lines.append(f"[{i}] ({label}) {chunk.text}")
    return "\n".join(lines)
