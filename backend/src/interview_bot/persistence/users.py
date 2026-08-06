"""User account persistence: fetch-or-create by Google identity.

Plain database mechanics over `User`, mirroring `persistence.sessions`'s style.
Takes plain fields rather than a `GoogleIdentity` so this module stays
decoupled from `integrations.google_auth` (a vendor-specific type) — the same
layering `persistence.sessions.create` follows by taking a domain `JobProfile`
rather than an LLM extraction model.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from interview_bot.persistence.models import User


def get_by_google_sub(db: Session, google_sub: str) -> User | None:
    return db.query(User).filter(User.google_sub == google_sub).first()


def get_or_create(
    db: Session,
    *,
    google_sub: str,
    email: str,
    name: str | None,
    picture: str | None,
) -> tuple[User, bool]:
    """Fetch the user for this Google account, or create one.

    Returns `(user, is_new)` so the caller can grant signup credits exactly
    once. Does not commit — the caller owns the transaction (it also needs to
    apply a signup grant before persisting).
    """
    user = get_by_google_sub(db, google_sub)
    if user is not None:
        user.display_name = name
        user.picture_url = picture
        user.email = email
        user.last_login_at = datetime.now(UTC)
        return user, False

    user = User(
        id=str(uuid.uuid4()),
        google_sub=google_sub,
        email=email,
        display_name=name,
        picture_url=picture,
    )
    db.add(user)
    return user, True
