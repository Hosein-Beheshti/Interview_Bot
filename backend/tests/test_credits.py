"""Tests for the HTTP-facing credit dependency (api/credits.py) — the 402
mapping and the FastAPI dependency factory. The underlying atomic debit
itself is `persistence.users.debit_credits`, tested in test_users.py; this
file exercises the thin wrapper end to end (mocked db, same as
test_limits.py's no-DB style) so both layers stay covered."""
from unittest.mock import MagicMock

import pytest

from interview_bot.api import credits
from interview_bot.config import settings


def _db(*, returns) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.first.return_value = returns
    return db


def _unreachable(*args, **kwargs):
    raise AssertionError("the database must not be consulted on this path")


def test_debit_returns_the_new_balance_on_success():
    db = _db(returns=(15,))
    assert credits.debit(db, "u1", 5) == 15
    db.commit.assert_called_once()


def test_debit_raises_402_on_insufficient_balance():
    db = _db(returns=None)
    with pytest.raises(credits.HTTPException) as excinfo:
        credits.debit(db, "u1", 5)
    assert excinfo.value.status_code == 402
    # Still commits: the SELECT/UPDATE-that-matched-nothing must not leave a
    # dangling open transaction.
    db.commit.assert_called_once()


def test_402_detail_names_the_cost_and_the_balance():
    """"Insufficient credits" leaves the caller guessing how short they are."""
    db = _db(returns=None)
    db.get.return_value = MagicMock(credits=2)
    with pytest.raises(credits.HTTPException) as excinfo:
        credits.debit(db, "u1", 8)
    assert excinfo.value.detail == "This costs 8 credits and your balance is 2."


def test_balance_of_reads_zero_for_a_user_that_no_longer_exists():
    db = MagicMock()
    db.get.return_value = None
    assert credits.balance_of(db, "u1") == 0


def test_debit_is_a_no_op_for_a_non_positive_cost():
    db = MagicMock()
    db.execute = _unreachable
    assert credits.debit(db, "u1", 0) == -1


def test_require_is_a_no_op_when_credits_are_not_required(monkeypatch):
    monkeypatch.setattr(settings, "require_credits_to_start_session", False)
    dependency = credits.require(5)
    user = MagicMock(id="u1")
    db = MagicMock()
    db.execute = _unreachable
    dependency(user, db)  # must not raise / must not touch the database


def test_require_debits_when_credits_are_required(monkeypatch):
    monkeypatch.setattr(settings, "require_credits_to_start_session", True)
    dependency = credits.require(5)
    user = MagicMock(id="u1")
    db = _db(returns=(10,))
    dependency(user, db)
    db.execute.assert_called_once()


def test_grant_signup_credits_sets_the_configured_amount(monkeypatch):
    monkeypatch.setattr(settings, "signup_credit_grant", 20)
    user = MagicMock()
    credits.grant_signup_credits(user)
    assert user.credits == 20


def test_grant_signup_credits_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "signup_credit_grant", 0)
    user = MagicMock(credits=999)
    credits.grant_signup_credits(user)
    assert user.credits == 999
