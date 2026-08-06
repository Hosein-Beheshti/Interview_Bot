"""Tests for user persistence (persistence/users.py). No real database — the
atomic-debit primitive is exercised with a mocked ORM Session, matching
test_limits.py's style."""
from unittest.mock import MagicMock

from interview_bot.persistence import users as user_store


def _db(*, returns) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.first.return_value = returns
    return db


def _unreachable(*args, **kwargs):
    raise AssertionError("the database must not be consulted on this path")


def test_debit_credits_returns_the_new_balance_on_success():
    db = _db(returns=(15,))
    assert user_store.debit_credits(db, "u1", 5) == 15
    db.commit.assert_called_once()


def test_debit_credits_returns_none_on_insufficient_balance():
    db = _db(returns=None)
    assert user_store.debit_credits(db, "u1", 5) is None
    # Still commits: a matched-nothing UPDATE must not leave a dangling
    # open transaction.
    db.commit.assert_called_once()


def test_debit_credits_is_a_no_op_for_a_non_positive_cost():
    db = MagicMock()
    db.execute = _unreachable
    assert user_store.debit_credits(db, "u1", 0) == -1


def test_get_or_create_creates_a_new_user_for_an_unknown_google_sub():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    user, is_new = user_store.get_or_create(
        db, google_sub="sub-1", email="jane@example.com", name="Jane", picture=None
    )

    assert is_new is True
    assert user.google_sub == "sub-1"
    assert user.email == "jane@example.com"
    db.add.assert_called_once_with(user)


def test_get_or_create_refreshes_an_existing_user():
    existing = MagicMock(google_sub="sub-1")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    user, is_new = user_store.get_or_create(
        db, google_sub="sub-1", email="new-email@example.com", name="New Name", picture="pic-url"
    )

    assert is_new is False
    assert user is existing
    assert user.email == "new-email@example.com"
    assert user.display_name == "New Name"
    assert user.picture_url == "pic-url"
    db.add.assert_not_called()
