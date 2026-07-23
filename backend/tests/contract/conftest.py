"""Offline guarantees for every contract test in this directory.

The single autouse fixture forces `transport_mode="replay"` and neutralizes the
tracing backend, so these tests:
  * serve all provider responses from committed cassettes (no network),
  * never construct a provider client (no API keys required),
  * emit no traces regardless of the local `.env`.

Scope is `tests/contract/` only — the existing pure unit tests are untouched.
"""
from __future__ import annotations

import pytest

from interview_bot.config import settings
from interview_bot.llm.registry import get_provider
from interview_bot.telemetry import tracer


@pytest.fixture(autouse=True)
def _offline_replay(monkeypatch):
    monkeypatch.setattr(settings, "transport_mode", "replay")
    # Tracing is best-effort and cannot change outputs, but an enabled-but-
    # unreachable Langfuse backend would add network latency; pin it to no-op.
    monkeypatch.setattr(tracer, "_backend", tracer.NoopBackend())
    # The provider factory is cached; drop any instance a prior (non-replay)
    # test built so replay never touches a live client.
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()
