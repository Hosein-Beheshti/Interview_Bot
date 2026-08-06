"""Per-user credit balance — the identity-keyed counterpart to api/limits.py's
IP-keyed rate limits.

A separate module, not folded into `limits.py`: that file is IP-keyed
admission control over windowed counters for an unauthenticated API; credits
are identity-keyed, permanent-balance metering — a different mechanism, kept
in its own file per this codebase's one-file-per-concern convention.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from interview_bot.api.auth import get_current_user
from interview_bot.config import settings
from interview_bot.logger import logger
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import User

_DEBIT = text(
    "UPDATE users SET credits = credits - :cost WHERE id = :id AND credits >= :cost "
    "RETURNING credits"
)


def debit(db: Session, user_id: str, cost: int) -> int:
    """Atomically deduct `cost` credits. Raises 402 if the balance is short.

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
    if result is None:
        logger.info(f"Insufficient credits | user={user_id} | cost={cost}")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient credits."
        )
    return result[0]


def require(cost: int) -> Callable[..., None]:
    """A route dependency for endpoints that always create a session (only
    POST /sessions qualifies — /chat and /cv/upload create a session only
    sometimes, so they call `debit()` directly instead of using this)."""

    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
        if settings.require_credits_to_start_session:
            debit(db, user.id, cost)

    return dependency


def grant_signup_credits(user: User) -> None:
    """Set the free signup allowance. Caller must ensure this runs only once,
    at first-login user creation — not on every login."""
    if settings.signup_credit_grant > 0:
        user.credits = settings.signup_credit_grant
