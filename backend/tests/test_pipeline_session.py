"""Tests for the session-setup flow's credit gate (pipeline/session.py)."""
import asyncio
from types import SimpleNamespace

import pytest

from interview_bot.config import settings
from interview_bot.domain.profile import JobProfile
from interview_bot.pipeline import session as session_flow


def test_create_from_context_raises_when_credits_are_insufficient(monkeypatch):
    monkeypatch.setattr(settings, "require_credits_to_start_session", True)
    monkeypatch.setattr(
        session_flow.user_store, "debit_credits", lambda db, user_id, cost: None
    )
    monkeypatch.setattr(
        session_flow, "build_profile", _unreachable_async, raising=False
    )

    with pytest.raises(session_flow.InsufficientCreditsError):
        asyncio.run(
            session_flow.create_from_context(
                db=object(), job_context="Backend role.", role=None, user_id="u1"
            )
        )


def test_create_from_context_skips_the_credit_check_when_disabled(monkeypatch):
    # This is the kill switch documented on the setting itself: with it off,
    # session creation must succeed even for a user with zero (or negative)
    # credits, and the debit path must not be touched at all.
    monkeypatch.setattr(settings, "require_credits_to_start_session", False)
    monkeypatch.setattr(session_flow.user_store, "debit_credits", _unreachable)
    monkeypatch.setattr(
        session_flow, "build_profile", _fake_build_profile, raising=False
    )
    monkeypatch.setattr(session_flow, "build_plan", _fake_build_plan, raising=False)
    monkeypatch.setattr(
        session_flow.store,
        "create",
        lambda db, **kwargs: SimpleNamespace(session_id="s1"),
        raising=False,
    )
    monkeypatch.setattr(session_flow, "set_session", lambda session_id: None, raising=False)

    asyncio.run(
        session_flow.create_from_context(
            db=object(), job_context="Backend role.", role=None, user_id="u1"
        )
    )


def _unreachable(*args, **kwargs):
    raise AssertionError("the credit check must not run when it's disabled")


async def _unreachable_async(*args, **kwargs):
    raise AssertionError("no LLM call should happen before the credit check")


async def _fake_build_profile(job_context):
    return JobProfile(role="Software Engineer")


async def _fake_build_plan(profile, num_questions):
    return None
