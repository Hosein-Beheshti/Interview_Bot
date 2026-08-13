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

from sqlalchemy import text
from sqlalchemy.orm import Session

from interview_bot.persistence.models import User

_DEBIT = text(
    "UPDATE users SET credits = credits - :cost WHERE id = :id AND credits >= :cost "
    "RETURNING credits"
)

_REFUND = text("UPDATE users SET credits = credits + :cost WHERE id = :id RETURNING credits")


def get_by_google_sub(db: Session, google_sub: str) -> User | None:
    return db.query(User).filter(User.google_sub == google_sub).first()


def get(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


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


def debit_credits(db: Session, user_id: str, cost: int) -> int | None:
    """Atomically deduct `cost` credits. Returns the new balance, or `None` if
    the balance was insufficient; the HTTP-facing 402 mapping is the caller's
    job, not this module's — this is plain persistence, no HTTP concerns.

    A single guarded UPDATE is race-safe on its own: Postgres holds an
    implicit per-row lock for the statement's duration, and `credits >= :cost`
    is evaluated against that locked row, so two concurrent debits against the
    same account serialize correctly with no extra round trip. This differs
    from `persistence.sessions.get(..., lock=True)`'s SELECT-then-UPDATE
    pattern, which needs an explicit lock because there's a gap between the
    read and a later, separate write — a debit has no such gap.
    """
    if cost <= 0:
        return -1
    result = db.execute(_DEBIT, {"id": user_id, "cost": cost}).first()
    db.commit()
    return result[0] if result is not None else None


def refund_credits(db: Session, user_id: str, cost: int) -> int | None:
    """Give back `cost` credits previously taken by `debit_credits`.

    The compensating half of the debit. A debit cannot share a transaction with
    the work it pays for: that work is several seconds of provider calls, and
    holding the user row locked across them would serialize every one of that
    user's requests behind the slowest one. So the debit commits immediately and
    a failure afterwards is repaired here instead.

    Unconditional — unlike a debit there is no balance to check, so the only way
    this returns `None` is a user row that no longer exists.
    """
    if cost <= 0:
        return -1
    result = db.execute(_REFUND, {"id": user_id, "cost": cost}).first()
    db.commit()
    return result[0] if result is not None else None
