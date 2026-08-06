"""Tests for the session-setup flow's credit gate (pipeline/session.py)."""
import asyncio

import pytest

from interview_bot.pipeline import session as session_flow


def test_create_from_context_raises_when_credits_are_insufficient(monkeypatch):
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


async def _unreachable_async(*args, **kwargs):
    raise AssertionError("no LLM call should happen before the credit check")
