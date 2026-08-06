"""Tests for login sessions (api/auth.py). No real database — the ORM Session
is a small hand-built double, mirroring test_limits.py's SimpleNamespace-based
Request double."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from interview_bot.api import auth
from interview_bot.config import settings
from interview_bot.persistence.models import User, UserSession


def _request(cookie: str | None):
    cookies = {settings.session_cookie_name: cookie} if cookie else {}
    return SimpleNamespace(cookies=cookies)


def _db(*, user_session=None, user=None):
    def query(model):
        chain = MagicMock()
        if model is UserSession:
            chain.filter.return_value.first.return_value = user_session
        elif model is User:
            chain.filter.return_value.first.return_value = user
        else:
            chain.filter.return_value.first.return_value = None
        return chain

    db = MagicMock()
    db.query.side_effect = query
    return db


def _unreachable(*args, **kwargs):
    raise AssertionError("the database must not be consulted on this path")


# --------------------------------------------------------------------------- #
# Cookie attributes
# --------------------------------------------------------------------------- #
def test_cookie_is_lax_and_insecure_outside_production(monkeypatch):
    monkeypatch.setattr(settings, "railway_environment", "")
    kwargs = auth._cookie_kwargs()
    assert kwargs["secure"] is False
    assert kwargs["samesite"] == "lax"


def test_cookie_is_none_and_secure_in_production(monkeypatch):
    monkeypatch.setattr(settings, "railway_environment", "production")
    kwargs = auth._cookie_kwargs()
    assert kwargs["secure"] is True
    assert kwargs["samesite"] == "none"


# --------------------------------------------------------------------------- #
# Token hashing
# --------------------------------------------------------------------------- #
def test_hash_token_is_deterministic():
    assert auth.hash_token("abc") == auth.hash_token("abc")


def test_hash_token_differs_for_different_tokens():
    assert auth.hash_token("abc") != auth.hash_token("xyz")


def test_hash_token_never_returns_the_raw_token():
    assert auth.hash_token("abc") != "abc"


# --------------------------------------------------------------------------- #
# Naive-datetime defense (SQLite doesn't round-trip tzinfo the way Postgres's
# timestamptz columns do)
# --------------------------------------------------------------------------- #
def test_as_aware_utc_leaves_an_aware_datetime_unchanged():
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    assert auth._as_aware_utc(dt) == dt


def test_as_aware_utc_attaches_utc_to_a_naive_datetime():
    dt = datetime(2026, 1, 1)
    assert auth._as_aware_utc(dt) == datetime(2026, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# get_current_user
# --------------------------------------------------------------------------- #
def test_get_current_user_rejects_a_missing_cookie():
    request = _request(None)
    db = _db()
    db.query.side_effect = _unreachable
    with pytest.raises(auth.HTTPException) as excinfo:
        auth.get_current_user(request, db)
    assert excinfo.value.status_code == 401


def test_get_current_user_rejects_an_unknown_token():
    request = _request("some-token")
    db = _db(user_session=None)
    with pytest.raises(auth.HTTPException) as excinfo:
        auth.get_current_user(request, db)
    assert excinfo.value.status_code == 401


def test_get_current_user_rejects_an_expired_session():
    request = _request("some-token")
    expired = SimpleNamespace(
        user_id="u1", expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    db = _db(user_session=expired)
    with pytest.raises(auth.HTTPException) as excinfo:
        auth.get_current_user(request, db)
    assert excinfo.value.status_code == 401


def test_get_current_user_returns_the_user_for_a_valid_session():
    request = _request("some-token")
    live = SimpleNamespace(user_id="u1", expires_at=datetime.now(UTC) + timedelta(days=1))
    the_user = SimpleNamespace(id="u1", email="jane@example.com")
    db = _db(user_session=live, user=the_user)

    result = auth.get_current_user(request, db)

    assert result is the_user


# --------------------------------------------------------------------------- #
# delete_current_session
# --------------------------------------------------------------------------- #
def test_delete_current_session_is_a_no_op_without_a_cookie():
    request = _request(None)
    db = _db()
    db.query.side_effect = _unreachable
    auth.delete_current_session(request, db)  # must not raise
