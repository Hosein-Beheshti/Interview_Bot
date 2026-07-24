"""CV upload and indexing endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from interview_bot.api.schemas import CVStatusResponse, CVUploadResponse
from interview_bot.config import settings
from interview_bot.integrations import cv_parser
from interview_bot.logger import logger
from interview_bot.persistence import sessions as session_store
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import InterviewSession
from interview_bot.pipeline import session as session_flow
from interview_bot.retrieval import rag

router = APIRouter(prefix="/cv", tags=["cv"])


@router.post("/upload", response_model=CVUploadResponse)
async def upload_cv(
    file: UploadFile = File(...),
    session_id: str | None = None,
    role: str | None = None,
    job_context: str | None = None,
    db: Session = Depends(get_db),
) -> CVUploadResponse:
    content = await file.read()
    _validate_upload(file.filename or "", content)

    try:
        parsed = cv_parser.parse(file.filename or "cv", content)
    except cv_parser.CVParseError as e:
        logger.warning(f"CV parse failed | filename={file.filename} | error={e}")
        raise HTTPException(status_code=400, detail=str(e)) from e

    session = await _resolve_session(session_id, role, job_context, db)

    try:
        result = await rag.index_cv(session.session_id, parsed)
    except Exception as e:
        logger.error(f"CV indexing failed | session={session.session_id} | error={e}")
        raise HTTPException(status_code=502, detail="Failed to index CV") from e

    session.cv_filename = parsed.filename
    session.cv_indexed_at = datetime.utcnow()
    session.cv_sections = result.sections
    session.cv_full_text = parsed.text
    session.candidate_name = cv_parser.extract_name(parsed.text)
    db.add(session)
    db.commit()

    return CVUploadResponse(
        session_id=session.session_id,
        filename=parsed.filename,
        chunk_count=result.chunk_count,
        sections=result.sections,
    )


@router.get("/{session_id}", response_model=CVStatusResponse)
async def cv_status(session_id: str, db: Session = Depends(get_db)) -> CVStatusResponse:
    session = session_store.get(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return CVStatusResponse(
        session_id=session.session_id,
        has_cv=session.has_cv,
        filename=session.cv_filename,
        sections=session.cv_sections,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_cv(session_id: str, db: Session = Depends(get_db)) -> Response:
    session = session_store.get(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    rag.delete_index(session_id)
    session.cv_filename = None
    session.cv_indexed_at = None
    session.cv_sections = None
    session.cv_full_text = None
    session.candidate_name = None
    db.add(session)
    db.commit()
    return Response(status_code=204)


def _validate_upload(filename: str, content: bytes) -> None:
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > settings.cv_max_bytes:
        limit_mb = settings.cv_max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File exceeds {limit_mb}MB limit")
    if cv_parser.extension(filename) not in cv_parser.SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file type. Use PDF, DOCX, or TXT.")


async def _resolve_session(
    session_id: str | None, role: str | None, job_context: str | None, db: Session
) -> InterviewSession:
    if session_id:
        session = session_store.get(db, session_id)
        if session:
            return session
    return await session_flow.create_from_context(db, job_context=job_context, role=role)
