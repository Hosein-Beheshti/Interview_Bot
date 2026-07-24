"""Admission control for a public, unauthenticated API.

Every endpoint here spends money with a third party on each call — model tokens,
Deepgram minutes, embedding requests — and none of them requires a credential.
Two independent caps make that safe to publish:

  * per-IP quotas, which stop one caller monopolising the demo, and
  * an instance-wide daily token ceiling, which bounds the bill even when a
    caller spreads their requests across many addresses.

The ceiling is deliberately the cruder of the two. Per-IP limits assume the IP
means something; the ceiling assumes nothing at all, so it is what actually
guarantees the invoice has a maximum.

Quotas are charged before the work runs, so a request that fails still counts —
retry loops are the thing being defended against.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status

from interview_bot.config import settings
from interview_bot.logger import logger
from interview_bot.persistence import usage

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

_GLOBAL = "global"
_TOKENS_BUCKET = "model_tokens"


@dataclass(frozen=True)
class Quota:
    """An allowance of `limit` units per `window`, metered under `bucket`."""

    bucket: str
    limit: int
    window: timedelta


def client_ip(request: Request) -> str:
    """The caller's address, as the rate limiter should attribute it.

    X-Forwarded-For is caller-supplied and trivially spoofed, so it is honoured
    only when `trust_proxy_headers` says a proxy is definitely in front of us and
    therefore rewriting it. Otherwise the socket address is the only fact.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def charge(quota: Quota, subject: str, *, amount: int = 1) -> None:
    """Charge `amount` against `quota`, raising 429 once the allowance is gone."""
    if not settings.rate_limit_enabled or quota.limit <= 0:
        return
    total = usage.consume(quota.bucket, subject, quota.window, amount=amount)
    if total > quota.limit:
        logger.warning(
            f"Rate limit hit | bucket={quota.bucket} | subject={subject} | "
            f"total={total} | limit={quota.limit}"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(_seconds_until_window_end(quota.window))},
        )


def enforce(quota: Quota) -> Callable[[Request], None]:
    """A FastAPI dependency charging one unit of `quota` to the caller's IP."""

    def dependency(request: Request) -> None:
        charge(quota, client_ip(request))

    return dependency


def require_token_budget() -> None:
    """Reject the request if today's instance-wide token ceiling is already spent.

    A pre-flight check, not a reservation: a turn's token cost is unknown until
    the provider answers, so the ceiling can be overshot by roughly one turn.
    That is the intended trade — the alternative is estimating cost up front and
    being wrong in the expensive direction.
    """
    if not settings.rate_limit_enabled or settings.daily_token_ceiling <= 0:
        return
    spent = usage.current(_TOKENS_BUCKET, _GLOBAL, DAY)
    if spent >= settings.daily_token_ceiling:
        logger.error(
            f"Daily token ceiling reached | spent={spent} | "
            f"ceiling={settings.daily_token_ceiling}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The demo has reached its daily usage limit. Please try again tomorrow.",
            headers={"Retry-After": str(_seconds_until_window_end(DAY))},
        )


def record_tokens(totals: dict[str, int]) -> None:
    """Add a completed unit of work's token usage to today's ceiling.

    Best-effort: metering must never turn a successful interview turn into an
    error the candidate sees.
    """
    if not settings.rate_limit_enabled or settings.daily_token_ceiling <= 0:
        return
    spent = sum(totals.values())
    if spent <= 0:
        return
    try:
        usage.consume(_TOKENS_BUCKET, _GLOBAL, DAY, amount=spent)
    except Exception as e:
        logger.warning(f"Could not record token usage | tokens={spent} | error={e}")


def _seconds_until_window_end(window: timedelta) -> int:
    ends_at = usage.window_start(window) + window
    return max(1, math.ceil((ends_at - datetime.now(UTC)).total_seconds()))


# The concrete quotas, one per paid operation.
SESSION_CREATION = Quota("session_create", settings.sessions_per_hour_per_ip, HOUR)
INTERVIEW_TURN = Quota("interview_turn", settings.turns_per_hour_per_ip, HOUR)
CV_UPLOAD = Quota("cv_upload", settings.cv_uploads_per_hour_per_ip, HOUR)
TRANSCRIPTION = Quota("transcribe", settings.transcriptions_per_hour_per_ip, HOUR)
# Charged in characters rather than calls: one long request costs as much as many
# short ones, so calls are the wrong unit.
TTS_CHARACTERS = Quota("tts_chars", settings.tts_chars_per_day_per_ip, DAY)
