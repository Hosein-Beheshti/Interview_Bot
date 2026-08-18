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


def test_client_ip_reads_the_hop_the_trusted_proxy_appended(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    # One trusted proxy: it appended the address it saw, so the real caller is
    # the last entry. Everything to its left is unverified.
    request = _request({"x-forwarded-for": "1.2.3.4, 10.0.0.9"}, host="10.0.0.1")
    assert limits.client_ip(request) == "10.0.0.9"


def test_client_ip_ignores_a_forged_prefix(monkeypatch):
    # The bypass this parsing exists to stop: a caller sends their own
    # X-Forwarded-For, the edge appends the real address, and reading the
    # leftmost entry would hand the caller a fresh rate-limit identity per
    # request just by varying what they send.
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    forged = _request({"x-forwarded-for": "9.9.9.9, 203.0.113.7"}, host="10.0.0.1")
    other = _request({"x-forwarded-for": "8.8.8.8, 203.0.113.7"}, host="10.0.0.1")
    assert limits.client_ip(forged) == limits.client_ip(other) == "203.0.113.7"


def test_client_ip_falls_back_when_the_chain_is_shorter_than_expected(monkeypatch):
    # Two trusted hops configured but only one entry present means the request
    # did not arrive through the assumed chain, so the header proves nothing.
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    request = _request({"x-forwarded-for": "1.2.3.4"}, host="10.0.0.1")
    assert limits.client_ip(request) == "10.0.0.1"


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
    monkeypatch.setattr(settings, "turns_per_hour_per_ip", 0)
    monkeypatch.setattr(usage, "consume", _unreachable)
    limits.charge(limits.INTERVIEW_TURN, "10.0.0.1")


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
    monkeypatch.setattr(settings, "sessions_per_hour_per_ip", 5)
    monkeypatch.setattr(usage, "consume", lambda *a, **k: 6)

    with pytest.raises(limits.HTTPException) as excinfo:
        limits.charge(limits.SESSION_CREATION, "10.0.0.1")

    assert excinfo.value.status_code == 429
    # A client that cannot tell when to come back just retries immediately.
    assert int(excinfo.value.headers["Retry-After"]) > 0


def test_charge_allows_the_request_that_lands_exactly_on_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "sessions_per_hour_per_ip", 5)
    monkeypatch.setattr(usage, "consume", lambda *a, **k: 5)
    limits.charge(limits.SESSION_CREATION, "10.0.0.1")


def test_token_budget_rejects_with_503_when_the_ceiling_is_spent(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "daily_token_ceiling", 1000)
    monkeypatch.setattr(usage, "current", lambda *a, **k: 1000)

    with pytest.raises(limits.HTTPException) as excinfo:
        limits.require_token_budget()

    # 503, not 429: the demo as a whole is out of budget, not this caller.
    assert excinfo.value.status_code == 503


# --------------------------------------------------------------------------- #
# Quotas resolve their allowance from config
# --------------------------------------------------------------------------- #
def test_every_quota_names_a_real_setting():
    # A Quota stores the *name* of its setting, so a typo would only surface on a
    # charged request. limits.py checks this at import; assert it here too so the
    # reason the check exists is visible in the tests.
    for quota in limits.QUOTAS:
        assert hasattr(settings, quota.setting), quota.bucket


def test_quota_limit_is_read_live_not_captured_at_import(monkeypatch):
    # The behaviour this design exists for: the configured number is the enforced
    # number. Capturing settings into the Quota at import made these diverge.
    monkeypatch.setattr(settings, "turns_per_hour_per_ip", 99)
    assert limits.INTERVIEW_TURN.limit == 99


def test_quota_buckets_are_unique():
    # Two quotas sharing a bucket would silently share one counter.
    buckets = [q.bucket for q in limits.QUOTAS]
    assert len(buckets) == len(set(buckets))


# --------------------------------------------------------------------------- #
# Token weighting
# --------------------------------------------------------------------------- #
_TOTALS = {
    "input_tokens": 1000,
    "output_tokens": 100,
    "cache_read_tokens": 5000,
    "cache_write_tokens": 200,
}


def test_default_weights_count_raw_volume():
    # The shipped defaults are all 1.0, so the ceiling counts exactly what the
    # plain sum used to count. Changing this is an admission-control change.
    assert limits.weighted_tokens(_TOTALS) == sum(_TOTALS.values())


def test_weights_can_make_the_ceiling_track_cost(monkeypatch):
    # Haiku 4.5 ratios: output is 5x input, a cache read ~0.1x, a write ~1.25x.
    monkeypatch.setattr(settings, "token_weight_input", 1.0)
    monkeypatch.setattr(settings, "token_weight_output", 5.0)
    monkeypatch.setattr(settings, "token_weight_cache_read", 0.1)
    monkeypatch.setattr(settings, "token_weight_cache_write", 1.25)
    # 1000 + 500 + 500 + 250
    assert limits.weighted_tokens(_TOTALS) == 2250


def test_unknown_token_field_is_charged_at_full_weight():
    # A token class the tracer starts reporting must never go silently uncounted.
    assert limits.weighted_tokens({"future_tokens": 42}) == 42


def test_weighted_tokens_floors_to_whole_units(monkeypatch):
    monkeypatch.setattr(settings, "token_weight_cache_read", 0.1)
    assert limits.weighted_tokens({"cache_read_tokens": 5}) == 0


def test_weighted_tokens_ignores_zero_and_negative_counts():
    assert limits.weighted_tokens({"input_tokens": 0, "output_tokens": -5}) == 0


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
