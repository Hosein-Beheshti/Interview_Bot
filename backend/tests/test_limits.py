"""Tests for admission control (api/limits.py, persistence/usage.py).

Only the parts that need no database: window arithmetic, client attribution, and
the disabled-path short circuits. Counter storage itself is exercised against a
real Postgres, not here.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from interview_bot.api import limits
from interview_bot.config import settings
from interview_bot.persistence import usage


def _request(headers: dict[str, str] | None = None, host: str | None = "10.0.0.1"):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=host) if host else None,
    )


# --------------------------------------------------------------------------- #
# Window arithmetic
# --------------------------------------------------------------------------- #
def test_window_start_floors_to_a_fixed_grid():
    now = datetime(2026, 7, 24, 13, 47, 31, tzinfo=UTC)
    assert usage.window_start(timedelta(hours=1), now=now) == datetime(
        2026, 7, 24, 13, 0, tzinfo=UTC
    )


def test_window_start_is_stable_within_a_window():
    window = timedelta(hours=1)
    first = usage.window_start(window, now=datetime(2026, 7, 24, 13, 0, 1, tzinfo=UTC))
    last = usage.window_start(window, now=datetime(2026, 7, 24, 13, 59, 59, tzinfo=UTC))
    assert first == last


def test_window_start_advances_at_the_boundary():
    window = timedelta(hours=1)
    before = usage.window_start(window, now=datetime(2026, 7, 24, 13, 59, 59, tzinfo=UTC))
    after = usage.window_start(window, now=datetime(2026, 7, 24, 14, 0, 0, tzinfo=UTC))
    assert after - before == window


# --------------------------------------------------------------------------- #
# Client attribution
# --------------------------------------------------------------------------- #
def test_client_ip_uses_socket_address_by_default(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    request = _request({"x-forwarded-for": "1.2.3.4"}, host="10.0.0.1")
    # The header is present but must be ignored: trusting it undefended would let
    # any caller reset their own rate limit by inventing an address.
    assert limits.client_ip(request) == "10.0.0.1"


def test_client_ip_reads_forwarded_header_when_behind_a_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _request({"x-forwarded-for": "1.2.3.4, 10.0.0.9"}, host="10.0.0.1")
    assert limits.client_ip(request) == "1.2.3.4"


def test_client_ip_falls_back_when_there_is_no_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    assert limits.client_ip(_request(host=None)) == "unknown"


# --------------------------------------------------------------------------- #
# Short circuits — these must not touch the database
# --------------------------------------------------------------------------- #
def test_charge_is_a_no_op_when_rate_limiting_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(usage, "consume", _unreachable)
    limits.charge(limits.INTERVIEW_TURN, "10.0.0.1")


def test_charge_is_a_no_op_for_a_zero_quota(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(usage, "consume", _unreachable)
    limits.charge(limits.Quota("anything", 0, limits.HOUR), "10.0.0.1")


def test_token_budget_is_skipped_when_the_ceiling_is_zero(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "daily_token_ceiling", 0)
    monkeypatch.setattr(usage, "current", _unreachable)
    limits.require_token_budget()


def _unreachable(*args, **kwargs):
    raise AssertionError("storage must not be consulted on the disabled path")


# --------------------------------------------------------------------------- #
# Enforcement
# --------------------------------------------------------------------------- #
def test_charge_raises_429_once_the_allowance_is_exceeded(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(usage, "consume", lambda *a, **k: 6)

    with pytest.raises(limits.HTTPException) as excinfo:
        limits.charge(limits.Quota("session_create", 5, limits.HOUR), "10.0.0.1")

    assert excinfo.value.status_code == 429
    # A client that cannot tell when to come back just retries immediately.
    assert int(excinfo.value.headers["Retry-After"]) > 0


def test_charge_allows_the_request_that_lands_exactly_on_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(usage, "consume", lambda *a, **k: 5)
    limits.charge(limits.Quota("session_create", 5, limits.HOUR), "10.0.0.1")


def test_token_budget_rejects_with_503_when_the_ceiling_is_spent(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "daily_token_ceiling", 1000)
    monkeypatch.setattr(usage, "current", lambda *a, **k: 1000)

    with pytest.raises(limits.HTTPException) as excinfo:
        limits.require_token_budget()

    # 503, not 429: the demo as a whole is out of budget, not this caller.
    assert excinfo.value.status_code == 503


def test_recording_token_usage_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "daily_token_ceiling", 1000)
    monkeypatch.setattr(usage, "consume", _boom)
    # Metering must not turn a successful interview turn into an error.
    limits.record_tokens({"input_tokens": 10, "output_tokens": 5})


def _boom(*args, **kwargs):
    raise RuntimeError("database unavailable")


# --------------------------------------------------------------------------- #
# Ceiling-breach alert webhook
# --------------------------------------------------------------------------- #
def test_alert_is_a_no_op_when_webhook_url_is_unset(monkeypatch):
    monkeypatch.setattr(settings, "alert_webhook_url", "")
    monkeypatch.setattr(limits.httpx, "post", _unreachable)
    limits._send_alert("daily ceiling reached")


def test_alert_webhook_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.com/hook")
    monkeypatch.setattr(limits.httpx, "post", _boom)
    limits._send_alert("daily ceiling reached")  # must not raise


def test_ceiling_breach_sends_exactly_one_alert_per_day(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "daily_token_ceiling", 1000)
    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.com/hook")
    monkeypatch.setattr(usage, "current", lambda *a, **k: 1000)

    alert_bucket_totals = iter([1, 2])
    monkeypatch.setattr(usage, "consume", lambda *a, **k: next(alert_bucket_totals))

    sent: list[str] = []
    monkeypatch.setattr(limits, "_send_alert", sent.append)

    for _ in range(2):
        with pytest.raises(limits.HTTPException):
            limits.require_token_budget()

    assert len(sent) == 1
