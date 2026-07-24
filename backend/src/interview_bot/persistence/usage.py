"""Fixed-window usage counters — the storage primitive under rate limits and budgets.

Postgres-backed rather than in-process: limits must hold across replicas and
survive a restart. An in-memory dict resets on every deploy, which is precisely
when abusing an endpoint is cheapest.

Fixed windows, not sliding: one upsert per check, nothing to prune per request,
and the worst case — a caller getting up to twice the limit by straddling a
window boundary — does not matter for what these limits defend against. Sliding
windows would mean storing and scanning individual events.

Counters are written on their own connection, committed independently of the
request's transaction: consumption must be recorded even when the request it was
charged for goes on to fail.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from interview_bot.persistence.database import engine

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_UPSERT = text(
    """
    INSERT INTO usage_counters (bucket, subject, window_start, amount)
    VALUES (:bucket, :subject, :window_start, :amount)
    ON CONFLICT (bucket, subject, window_start)
    DO UPDATE SET amount = usage_counters.amount + EXCLUDED.amount
    RETURNING amount
    """
)

_SELECT = text(
    """
    SELECT amount FROM usage_counters
    WHERE bucket = :bucket AND subject = :subject AND window_start = :window_start
    """
)


def window_start(window: timedelta, *, now: datetime | None = None) -> datetime:
    """The start of the window `now` falls in — instants floored to a fixed grid.

    Anchored to the Unix epoch rather than to first use, so every replica agrees
    on where a window begins without coordinating.
    """
    moment = now or datetime.now(UTC)
    elapsed = (moment - _EPOCH) // window
    return _EPOCH + elapsed * window


def consume(bucket: str, subject: str, window: timedelta, *, amount: int = 1) -> int:
    """Charge `amount` to this window's counter and return the resulting total."""
    with engine.begin() as conn:
        return int(
            conn.execute(
                _UPSERT,
                {
                    "bucket": bucket,
                    "subject": subject,
                    "window_start": window_start(window),
                    "amount": amount,
                },
            ).scalar_one()
        )


def current(bucket: str, subject: str, window: timedelta) -> int:
    """This window's total so far, without charging anything to it."""
    with engine.connect() as conn:
        total = conn.execute(
            _SELECT,
            {"bucket": bucket, "subject": subject, "window_start": window_start(window)},
        ).scalar()
    return int(total or 0)


def delete_windows_before(cutoff: datetime) -> int:
    """Drop counters for windows that closed before `cutoff`. Returns rows removed."""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM usage_counters WHERE window_start < :cutoff"),
            {"cutoff": cutoff},
        )
    return result.rowcount or 0
