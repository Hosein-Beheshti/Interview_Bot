"""Langfuse tracing backend (self-hosted).

The ONLY file that imports the Langfuse SDK. It targets the v3+ OpenTelemetry-style
client API (`start_as_current_span` / `start_as_current_generation` /
`update_current_generation` / `update_current_trace` / `flush`). If you upgrade or
swap the SDK, this is the single file to adjust — the rest of the app talks to the
provider-agnostic `TracingBackend` seam in `tracer.py`.

Robustness is deliberate: every SDK touch is guarded so a tracing fault degrades to
a no-op observation rather than surfacing in the request path.
"""
from __future__ import annotations

import contextlib
from typing import Any

from config import settings
from logger import logger

from .tracer import NULL_HANDLE, Handle, TracingBackend


class _LangfuseHandle(Handle):
    def __init__(self, observation: Any) -> None:
        self._obs = observation

    def set_output(self, output: Any) -> None:
        try:
            self._obs.update(output=output)
        except Exception as e:
            logger.debug(f"tracing: set_output failed: {e}")


class LangfuseBackend(TracingBackend):
    def __init__(self) -> None:
        from langfuse import Langfuse  # ImportError → caller falls back to no-op

        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            raise RuntimeError("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set")

        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info(f"Observability: Langfuse tracing enabled (host={settings.langfuse_host})")

    @contextlib.contextmanager
    def observation(self, kind: str, name: str, *, input: Any, metadata: dict | None):
        start = (
            getattr(self._client, "start_as_current_generation", None)
            if kind == "generation"
            else getattr(self._client, "start_as_current_span", None)
        )
        if start is None:
            yield NULL_HANDLE
            return

        # Enter the SDK context manager defensively; on any failure, hand back a
        # null handle so the traced body still runs untouched.
        try:
            cm = start(name=name, input=input, metadata=metadata)
            observation = cm.__enter__()
        except Exception as e:
            logger.debug(f"tracing: start {kind} failed: {e}")
            yield NULL_HANDLE
            return

        try:
            yield _LangfuseHandle(observation)
        except Exception as e:
            # The traced body (the real LLM/IO call) raised — let the span record
            # it, then re-raise so the application sees its own error unchanged.
            _safe_exit(cm, e)
            raise
        else:
            _safe_exit(cm, None)

    def update_current_generation(
        self,
        *,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        request_id: str | None = None,
        stop_reason: str | None = None,
        provider: str | None = None,
    ) -> None:
        usage = _usage_details(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
        meta = _compact(
            {"request_id": request_id, "stop_reason": stop_reason, "provider": provider}
        )
        kwargs: dict[str, Any] = {}
        if model is not None:
            kwargs["model"] = model
        if usage:
            kwargs["usage_details"] = usage
        if meta:
            kwargs["metadata"] = meta
        if not kwargs:
            return
        try:
            self._client.update_current_generation(**kwargs)
        except Exception as e:
            logger.debug(f"tracing: update_current_generation failed: {e}")

    def set_trace_attributes(self, **attrs: Any) -> None:
        cleaned = _compact(attrs)
        if not cleaned:
            return
        try:
            self._client.update_current_trace(**cleaned)
        except Exception as e:
            logger.debug(f"tracing: update_current_trace failed: {e}")

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as e:
            logger.debug(f"tracing: flush failed: {e}")


def _safe_exit(cm: Any, exc: BaseException | None) -> None:
    try:
        if exc is None:
            cm.__exit__(None, None, None)
        else:
            cm.__exit__(type(exc), exc, exc.__traceback__)
    except Exception as e:
        logger.debug(f"tracing: observation exit failed: {e}")


def _usage_details(
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int | None,
    cache_write_tokens: int | None,
) -> dict[str, int]:
    """Map normalized token counts to Langfuse's `usage_details` keys.

    Cache reads/writes are kept as separate keys so cost stays correct once
    prompt caching is enabled (cached input is far cheaper than fresh input).
    """
    return _compact(
        {
            "input": input_tokens,
            "output": output_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": cache_write_tokens,
        }
    )


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
