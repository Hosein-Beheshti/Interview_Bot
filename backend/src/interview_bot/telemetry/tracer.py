"""Tracing core: the provider-agnostic API and the backend seam.

Public helpers (re-exported from the package) are thin async context managers
that delegate to a `TracingBackend`. The backend is chosen once at import:
Langfuse when configured, otherwise a no-op. Every public call is wrapped so a
tracing failure can never propagate into the request path.
"""
from __future__ import annotations

import contextlib
import contextvars
from abc import ABC, abstractmethod
from typing import Any

from interview_bot.config import settings
from interview_bot.logger import logger


# --------------------------------------------------------------------------- #
# Handles — what a context manager yields. `set_output` records the result of
# the traced step; the no-op handle ignores it.
# --------------------------------------------------------------------------- #
class Handle(ABC):
    @abstractmethod
    def set_output(self, output: Any) -> None: ...


class _NullHandle(Handle):
    def set_output(self, output: Any) -> None:
        pass


NULL_HANDLE = _NullHandle()


# --------------------------------------------------------------------------- #
# Backend seam. A backend turns abstract observations into concrete trace data.
# `observation` MUST NOT raise — it returns a context manager that degrades to a
# null handle on any internal error.
# --------------------------------------------------------------------------- #
class TracingBackend(ABC):
    @abstractmethod
    def observation(self, kind: str, name: str, *, input: Any, metadata: dict | None):
        """A sync context manager yielding a `Handle`. `kind` is 'generation' | 'span'."""

    @abstractmethod
    def update_current_generation(self, **attrs: Any) -> None: ...

    @abstractmethod
    def set_trace_attributes(self, **attrs: Any) -> None: ...

    @abstractmethod
    def flush(self) -> None: ...


class NoopBackend(TracingBackend):
    """Used whenever tracing is disabled or the real backend fails to load."""

    @contextlib.contextmanager
    def observation(self, kind: str, name: str, *, input: Any, metadata: dict | None):
        yield NULL_HANDLE

    def update_current_generation(self, **attrs: Any) -> None:
        pass

    def set_trace_attributes(self, **attrs: Any) -> None:
        pass

    def flush(self) -> None:
        pass


def _build_backend() -> TracingBackend:
    if not settings.langfuse_enabled:
        return NoopBackend()
    try:
        from .langfuse_backend import LangfuseBackend

        return LangfuseBackend()
    except Exception as e:  # missing package, bad keys, unreachable host, …
        logger.warning(f"Observability: Langfuse unavailable ({e}); tracing is a no-op.")
        return NoopBackend()


# Chosen once at import. Swapping backends is a change to `_build_backend`.
_backend: TracingBackend = _build_backend()


# --------------------------------------------------------------------------- #
# Public API — async context managers + fire-and-forget recorders.
# --------------------------------------------------------------------------- #
@contextlib.asynccontextmanager
async def observe_turn(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    input: Any = None,
    metadata: dict | None = None,
):
    """Root trace for one unit of work (an interview turn, a session creation).

    Nested `observe_generation` / `observe_span` calls attach beneath it, and
    `session_id` groups sibling traces in the backend's session view.
    """
    with _backend.observation("span", name, input=input, metadata=metadata) as handle:
        if session_id is not None or user_id is not None:
            set_session(session_id, user_id=user_id)
        yield handle


@contextlib.asynccontextmanager
async def observe_generation(
    name: str,
    *,
    provider: str | None = None,
    input: Any = None,
    metadata: dict | None = None,
):
    """Trace one LLM call. The provider fills tokens/cost via `record_generation_usage`."""
    md = dict(metadata or {})
    if provider:
        md["provider"] = provider
    with _backend.observation("generation", name, input=input, metadata=md or None) as handle:
        yield handle


@contextlib.asynccontextmanager
async def observe_span(name: str, *, input: Any = None, metadata: dict | None = None):
    """Trace a non-LLM step (embedding, vector search, speech, sub-pipeline)."""
    with _backend.observation("span", name, input=input, metadata=metadata) as handle:
        yield handle


# Contextvar sink for `capture_generation_usage`: while set, every
# `record_generation_usage` payload is mirrored into it. Used by the transport
# waist to persist token counts into cassettes without the providers knowing
# anything about recording.
_usage_sink: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "usage_sink", default=None
)


@contextlib.contextmanager
def capture_generation_usage():
    """Collect `record_generation_usage` payloads into the yielded dict.

    Purely additive: the payload still flows to the tracing backend exactly as
    before. None-valued fields are dropped so the capture reflects what the
    provider actually reported.
    """
    sink: dict[str, Any] = {}
    token = _usage_sink.set(sink)
    try:
        yield sink
    finally:
        _usage_sink.reset(token)


TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")

# Second sink, summing rather than overwriting. `capture_generation_usage` records
# one call's usage for its cassette, so it replaces; metering a unit of work needs
# the total across every call it made, so this one adds.
_token_totals: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "token_totals", default=None
)


@contextlib.contextmanager
def accumulate_token_usage():
    """Sum token counts across every generation inside the block.

    The measurement behind the spend budget: one interview turn makes several
    provider calls (scoring, then the interviewer), and what a budget cares about
    is their total.
    """
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    token = _token_totals.set(totals)
    try:
        yield totals
    finally:
        _token_totals.reset(token)


def record_generation_usage(**attrs: Any) -> None:
    """Attach model/token/cost metadata to the currently-active generation.

    Called from inside a provider right after it receives the raw response.
    Normalized keyword fields (all optional): `model`, `input_tokens`,
    `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `request_id`,
    `stop_reason`, `provider`.
    """
    sink = _usage_sink.get()
    if sink is not None:
        sink.update({k: v for k, v in attrs.items() if v is not None})
    totals = _token_totals.get()
    if totals is not None:
        for field in TOKEN_FIELDS:
            value = attrs.get(field)
            if value:
                totals[field] += int(value)
    try:
        _backend.update_current_generation(**attrs)
    except Exception as e:
        logger.debug(f"tracing: record usage failed: {e}")


def set_session(session_id: str | None, *, user_id: str | None = None, **attrs: Any) -> None:
    """Tag the active trace with a session/user id (and optional extra attributes)."""
    try:
        _backend.set_trace_attributes(session_id=session_id, user_id=user_id, **attrs)
    except Exception as e:
        logger.debug(f"tracing: set session failed: {e}")


def shutdown() -> None:
    """Flush buffered events. Call on application shutdown so nothing is lost."""
    try:
        _backend.flush()
    except Exception as e:
        logger.debug(f"tracing: flush failed: {e}")
