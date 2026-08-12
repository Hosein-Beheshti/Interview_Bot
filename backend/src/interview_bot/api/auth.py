"""Login sessions — the identity counterpart to api/limits.py's admission control.

A logged-in user is named by an `HttpOnly` cookie holding a random bearer
token; only its SHA-256 hash is ever stored (`persistence.models.UserSession`),
so a database dump or stray read cannot hand out a usable session. Cookie
attributes (`Secure`/`SameSite`) key off `settings.railway_environment` — the
same "am I in production" signal already used for the CORS startup guard —
rather than a second, separate mechanism.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from interview_bot.config import settings
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import InterviewSession, User, UserSession


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_aware_utc(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC. Postgres's timestamptz columns are always
    tz-aware in production; this only guards a comparison that would otherwise
    raise if a session is ever read back naive."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _in_production() -> bool:
    return bool(settings.railway_environment)


def _cookie_kwargs() -> dict:
    """Cookie attributes shared by set and clear, so they can't drift apart.

    `secure` and `samesite` both key off the same production signal: prod
    serves frontend and backend from different Railway subdomains (cross-site,
    requiring SameSite=None, which itself requires Secure=True); local dev
    goes through Vite's same-origin proxy, so Lax with no Secure works there.
    """
    in_prod = _in_production()
    return {
        "httponly": True,
        "secure": in_prod,
        "samesite": "none" if in_prod else "lax",
        "path": "/",
    }


def create_user_session(db: Session, user: User) -> str:
    """Create a new login session for `user`. Returns the raw bearer token —
    the only time it exists outside the cookie; only its hash is stored."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.session_max_age_days),
        )
    )
    db.commit()
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_max_age_days * 86400,
        **_cookie_kwargs(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, **_cookie_kwargs())


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The logged-in user, or 401 if the cookie is missing, unknown, or expired."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")

    user_session = (
        db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).first()
    )
    if user_session is None or _as_aware_utc(user_session.expires_at) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")

    user = db.query(User).filter(User.id == user_session.user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
    return user


def require_owner(session: InterviewSession, user_id: str) -> None:
    """403 unless `session` belongs to `user_id`.

    Takes a bare id rather than a `User` so callers that only have the id on
    hand (e.g. `pipeline.session`'s lazy-create threading) don't need to load
    a full `User` just to check ownership.

    An unowned session (`user_id is None` — created before accounts existed) is
    denied to everyone rather than allowed to everyone. Those rows predate
    sign-in and can hold an uploaded CV and a full transcript, so leaving them
    world-readable is an open door that never closes on its own: it stays open
    for whatever remains of `session_retention_days`. Every path that creates a
    session now records an owner, so this only affects legacy rows.
    """
    if session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session")


def delete_current_session(request: Request, db: Session) -> None:
    """Delete the `UserSession` row named by the request's cookie, if any.

    Tolerates "already gone" — logging out an expired or absent session must
    not itself error, unlike `get_current_user`'s strict check.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return
    db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).delete()
    db.commit()
