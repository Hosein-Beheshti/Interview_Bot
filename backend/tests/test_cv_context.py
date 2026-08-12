"""Tests for the CV-context policy (retrieval/cv_context.py).

Two things matter here and neither needs a real vector store: which text reaches
the model (full CV vs. retrieved excerpts), and — for the retrieval path — what
the CV is searched *against*.
"""
import asyncio
from types import SimpleNamespace

import pytest

from interview_bot.config import settings
from interview_bot.retrieval import cv_context, rag


def _session(*, has_cv=True, full_text="short cv", role="ML Engineer"):
    return SimpleNamespace(
        session_id="s1",
        role=role,
        cv_full_text=full_text,
        has_cv=has_cv,
        messages=[],
    )


def _long_cv() -> str:
    """A CV past the full-text threshold, forcing the retrieval path."""
    return "x" * (settings.cv_full_text_max_chars + 1)


def _build(session, topic):
    return asyncio.run(cv_context.build_cv_context(session, topic))


@pytest.fixture
def captured_queries(monkeypatch):
    """Record what `retrieve` was asked for, without touching embeddings or pgvector."""
    queries: list[str] = []

    async def _fake_retrieve(session_id, query, top_k=None):
        queries.append(query)
        return "Relevant excerpts from the candidate's CV:\n[1] (Experience) ..."

    monkeypatch.setattr(rag, "retrieve", _fake_retrieve)
    return queries


def test_no_cv_yields_empty_context():
    ctx = _build(_session(has_cv=False), "anything")
    assert ctx.text == ""
    assert not ctx


def test_short_cv_goes_in_full_and_is_cacheable():
    ctx = _build(_session(full_text="a compact CV"), "topic")
    assert "a compact CV" in ctx.text
    # Identical on every turn, so it belongs in the cached prefix.
    assert ctx.stable is True


def test_long_cv_falls_back_to_retrieval_and_is_not_cacheable(captured_queries):
    ctx = _build(_session(full_text=_long_cv()), "feature stores")
    assert "Relevant excerpts" in ctx.text
    # Changes every turn — marking it cacheable would write a fresh cache entry
    # per turn, which costs more than not caching at all.
    assert ctx.stable is False


def test_retrieval_queries_the_topic_it_was_given(captured_queries):
    """The bug this guards: querying the CV with the question just asked would
    retrieve the slice being left behind, not the one about to be discussed."""
    _build(_session(full_text=_long_cv()), "counterfactual evaluation")
    assert captured_queries == ["counterfactual evaluation"]


def test_retrieval_falls_back_to_the_role_without_a_topic(captured_queries):
    _build(_session(full_text=_long_cv(), role="ML Engineer"), None)
    assert captured_queries == ["ML Engineer"]


def test_retrieval_failure_degrades_to_no_context(monkeypatch):
    async def _boom(session_id, query, top_k=None):
        raise RuntimeError("pgvector unavailable")

    monkeypatch.setattr(rag, "retrieve", _boom)
    ctx = _build(_session(full_text=_long_cv()), "topic")
    assert ctx.text == ""
