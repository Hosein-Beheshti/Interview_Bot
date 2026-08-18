"""Admission control for a public, unauthenticated API.

Every endpoint here spends money with a third party on each call — model tokens,
Deepgram minutes, embedding requests — and none of them requires a credential.
Two independent caps make that safe to publish:

  * per-IP quotas, which stop one caller monopolising the demo, and
  * an instance-wide daily token ceiling, which bounds spend even when a caller
    spreads their requests across many addresses.

The ceiling is deliberately the cruder of the two. Per-IP limits assume the IP
means something; the ceiling assumes nothing at all, so it is what actually
guarantees the invoice has a maximum.

Quotas are charged before the work runs, so a request that fails still counts —
retry loops are the thing being defended against.

Every allowance in here lives in `config.Settings`; a `Quota` stores the *name* of
its setting and reads it per charge, so nothing in this module hard-codes a
number and the configured value is always the enforced one.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException, Request, status

from interview_bot.config import settings
from interview_bot.logger import logger
from interview_bot.persistence import usage

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

_GLOBAL = "global"
_TOKENS_BUCKET = "model_tokens"
_ALERT_BUCKET = "ceiling_alert_sent"


@dataclass(frozen=True)
class Quota:
    """An allowance per `window`, metered under `bucket`.

    `setting` names the `Settings` field holding the allowance; `limit` resolves
    it on every charge rather than capturing the value when this module is
    imported. That keeps one source of truth — the configured number is always
    the enforced number — and makes the real quotas monkeypatchable in a test,
    which a captured int is not.
    """

    bucket: str
    setting: str
    window: timedelta

    @property
    def limit(self) -> int:
        return int(getattr(settings, self.setting))


def client_ip(request: Request) -> str:
    """The caller's address, as the rate limiter should attribute it.

    X-Forwarded-For is caller-supplied, so it is honoured only when
    `trust_proxy_headers` says a proxy is definitely in front of us. Even then
    the header is not trustworthy end to end: proxies *append*, so a caller can
    send `X-Forwarded-For: 1.2.3.4` and the edge will simply add the real address
    after it. Only the last `trusted_proxy_hops` entries were written by
    infrastructure we control, so the caller's address is the one that many
    places from the right — taking the leftmost entry instead would let anyone
    reset their own rate limit on every request.

    A header with fewer entries than expected means the request did not arrive
    through the assumed chain, so the socket address is the only fact left.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            index = len(hops) - settings.trusted_proxy_hops
            if 0 <= index < len(hops):
                return hops[index]
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
        if settings.alert_webhook_url and usage.consume(_ALERT_BUCKET, _GLOBAL, DAY) == 1:
            _send_alert(
                f"Interview Bot: daily token ceiling reached "
                f"({spent}/{settings.daily_token_ceiling})."
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The demo has reached its daily usage limit. Please try again tomorrow.",
            headers={"Retry-After": str(_seconds_until_window_end(DAY))},
        )


def _send_alert(message: str) -> None:
    """POST `message` to the configured webhook. Best-effort: a failed or
    unconfigured alert must never affect the request that triggered it."""
    if not settings.alert_webhook_url:
        return
    try:
        httpx.post(
            settings.alert_webhook_url,
            json={"text": message},
            timeout=settings.alert_webhook_timeout_seconds,
        )
    except Exception as e:
        logger.warning(f"Alert webhook failed | error={e}")


# Which setting weights which token class. Keys are the fields
# `telemetry.tracer.TOKEN_FIELDS` reports. A field absent from this map is charged
# at full weight, so a newly-reported token class can never go silently uncounted.
_TOKEN_WEIGHTS = {
    "input_tokens": "token_weight_input",
    "output_tokens": "token_weight_output",
    "cache_read_tokens": "token_weight_cache_read",
    "cache_write_tokens": "token_weight_cache_write",
}


def weighted_tokens(totals: Mapping[str, int]) -> int:
    """The units to charge for `totals`, applying the configured class weights.

    Floored to whole units, so a sub-1.0 weight on a small count can charge 0 —
    intended, since a weight below 1 says that class is meant to be near-free.
    """
    weighted = 0.0
    for field, count in totals.items():
        if count <= 0:
            continue
        setting = _TOKEN_WEIGHTS.get(field)
        weighted += count * (getattr(settings, setting) if setting else 1.0)
    return int(weighted)


def record_tokens(totals: Mapping[str, int]) -> None:
    """Add a completed unit of work's token usage to today's ceiling.

    Best-effort: metering must never turn a successful interview turn into an
    error the candidate sees.
    """
    if not settings.rate_limit_enabled or settings.daily_token_ceiling <= 0:
        return
    spent = weighted_tokens(totals)
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
SESSION_CREATION = Quota("session_create", "sessions_per_hour_per_ip", HOUR)
INTERVIEW_TURN = Quota("interview_turn", "turns_per_hour_per_ip", HOUR)
CV_UPLOAD = Quota("cv_upload", "cv_uploads_per_hour_per_ip", HOUR)
TRANSCRIPTION = Quota("transcribe", "transcriptions_per_hour_per_ip", HOUR)
# Charged in characters rather than calls: one long request costs as much as many
# short ones, so calls are the wrong unit.
TTS_CHARACTERS = Quota("tts_chars", "tts_chars_per_day_per_ip", DAY)

# Every quota, for introspection — reporting the effective limits, and the test
# that proves each one names a real setting.
QUOTAS: tuple[Quota, ...] = (
    SESSION_CREATION,
    INTERVIEW_TURN,
    CV_UPLOAD,
    TRANSCRIPTION,
    TTS_CHARACTERS,
)

def _check_quota_settings() -> None:
    """Fail at import if a quota names a setting that does not exist.

    Naming a setting instead of capturing its value costs one thing: a typo
    becomes an AttributeError on the first charged request rather than an error at
    definition. Pay for it here so a bad name cannot reach production.
    """
    for quota in QUOTAS:
        if not hasattr(settings, quota.setting):
            raise AttributeError(
                f"Quota {quota.bucket!r} names unknown setting {quota.setting!r}"
            )


_check_quota_settings()
