"""LLM & pipeline observability (distributed tracing).

A self-contained, provider-agnostic seam over a tracing backend (currently
self-hosted Langfuse). The rest of the app only uses these helpers:

    observe_turn(...)              # root trace for one unit of work, tagged by session
    observe_generation(...)        # one LLM call (model, prompt, completion, latency)
    record_generation_usage(...)   # a provider reports tokens / request_id / stop_reason
    observe_span(...)              # a non-LLM step (embedding, vector search, speech)
    set_session(...)               # tag the active trace with a session/user id
    shutdown()                     # flush buffered events (call on app shutdown)

Design contract:
  * Best-effort. If tracing is disabled (no LANGFUSE_* config) or the backend
    errors, every call degrades to a no-op and NEVER affects the request path.
  * Provider-agnostic. Adding an LLM provider needs one line — a call to
    `record_generation_usage(...)` — matching what the existing providers do.
  * Backend-swappable. All Langfuse-specific code lives in `langfuse_backend.py`;
    implement `TracingBackend` and select it in `tracer.py` to use something else.
"""
from .tracer import (
    capture_generation_usage,
    observe_generation,
    observe_span,
    observe_turn,
    record_generation_usage,
    set_session,
    shutdown,
)

__all__ = [
    "observe_turn",
    "observe_generation",
    "observe_span",
    "capture_generation_usage",
    "record_generation_usage",
    "set_session",
    "shutdown",
]
