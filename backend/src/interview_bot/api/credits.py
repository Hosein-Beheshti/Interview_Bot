"""Per-user credit balance — the identity-keyed counterpart to api/limits.py's
IP-keyed rate limits.

A separate module, not folded into `limits.py`: that file is IP-keyed
admission control over windowed counters for an unauthenticated API; credits
are identity-keyed, permanent-balance metering — a different mechanism, kept
in its own file per this codebase's one-file-per-concern convention.

The actual debit is plain persistence (`persistence.users.debit_credits`) —
this module only adds the HTTP-facing 402 mapping and the FastAPI dependency
factory, so `pipeline.session` (which also needs to debit, for /chat's and
/cv/upload's lazy session creation) can call the persistence function
directly without importing anything from `api` — dependencies point inward,
never the other way.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from interview_bot.api.auth import get_current_user
from interview_bot.config import settings
from interview_bot.persistence import users as user_store
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import User


def debit(db: Session, user_id: str, cost: int) -> int:
    """Atomically deduct `cost` credits. Raises 402 if the balance is short."""
    result = user_store.debit_credits(db, user_id, cost)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient credits."
        )
    return result


def require(cost: int) -> Callable[..., None]:
    """A route dependency for endpoints that always create a session (only
    POST /sessions qualifies — /chat and /cv/upload create a session only
    sometimes, so they call `persistence.users.debit_credits` directly via
    `pipeline.session.create_from_context` instead of using this)."""

    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
        if settings.require_credits_to_start_session:
            debit(db, user.id, cost)

    return dependency


def grant_signup_credits(user: User) -> None:
    """Set the free signup allowance. Caller must ensure this runs only once,
    at first-login user creation — not on every login."""
    if settings.signup_credit_grant > 0:
        user.credits = settings.signup_credit_grant
