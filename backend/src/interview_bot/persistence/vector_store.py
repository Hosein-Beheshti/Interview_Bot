"""pgvector-backed vector store.

Uses the existing Postgres instance (extension `vector`) so we have a single
source of truth for both relational data and embeddings. Each chunk is scoped
to a session and retrieved via cosine distance.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select

from interview_bot.persistence.database import SessionLocal
from interview_bot.persistence.models import CVChunk


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    section: str
    distance: float


def upsert(
    session_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
    sections: list[str],
) -> None:
    if not (len(chunks) == len(embeddings) == len(sections)):
        raise ValueError("chunks, embeddings, and sections must be the same length")

    with SessionLocal() as db:
        db.execute(delete(CVChunk).where(CVChunk.session_id == session_id))
        db.add_all(
            CVChunk(
                session_id=session_id,
                chunk_index=i,
                section=section,
                content=content,
                embedding=embedding,
            )
            # strict=True: the three lists were just checked to be the same
            # length, so a mismatch here is a bug that should surface rather than
            # silently drop the tail of the CV.
            for i, (content, embedding, section) in enumerate(
                zip(chunks, embeddings, sections, strict=True)
            )
        )
        db.commit()


def query(session_id: str, embedding: list[float], top_k: int) -> list[RetrievedChunk]:
    with SessionLocal() as db:
        distance = CVChunk.embedding.cosine_distance(embedding).label("distance")
        rows = db.execute(
            select(CVChunk.content, CVChunk.section, distance)
            .where(CVChunk.session_id == session_id)
            .order_by(distance)
            .limit(top_k)
        ).all()
    return [
        RetrievedChunk(text=content, section=section, distance=float(dist))
        for content, section, dist in rows
    ]


def delete_session(session_id: str) -> None:
    with SessionLocal() as db:
        db.execute(delete(CVChunk).where(CVChunk.session_id == session_id))
        db.commit()
