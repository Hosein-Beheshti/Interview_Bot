"""pgvector-backed vector store.

Uses the existing Postgres instance (extension `vector`) so we have a single
source of truth for both relational data and embeddings. Each chunk is scoped
to a session and retrieved via cosine distance.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from database import SessionLocal, engine
from models.interview import CVChunk


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    section: str
    distance: float


def ensure_extension() -> None:
    """Enable the pgvector extension. Idempotent; safe to call on startup."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


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
            for i, (content, embedding, section) in enumerate(
                zip(chunks, embeddings, sections)
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
