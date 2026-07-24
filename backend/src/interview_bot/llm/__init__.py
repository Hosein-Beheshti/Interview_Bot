"""LLM facade.

The rest of the app imports `llm.generate`, `llm.generate_structured`, and
`llm.parse` — a stable, provider-agnostic seam. Each call delegates to whichever
backend `settings.llm_provider` selects (Claude, Gemini, …). Switching providers
is a config change: set LLM_PROVIDER and the matching API key; nothing here or
upstream changes. To add a backend, implement `LLMProvider` under
`interview_bot/llm/` and register it in registry.py.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel

from interview_bot.config import settings
from interview_bot.telemetry import observe_generation

from . import transport
from .registry import get_provider


def active_model() -> str:
    """The model name the configured provider will actually call."""
    return settings.gemini_model if settings.llm_provider == "gemini" else settings.model


async def generate(
    messages: list[dict],
    system: str,
    *,
    cache_prefix: str | None = None,
    temperature: float | None = None,
    operation: str = "llm.generate",
) -> str:
    """Generate a free-text assistant reply.

    `cache_prefix` is turn-invariant system text (role guidance, the candidate's
    CV) that the provider may mark for prompt caching; `system` is the volatile
    remainder (this turn's instruction). When `cache_prefix` is None, `system` is
    sent as-is. `temperature` defaults to `settings.generation_temperature`.
    `operation` is the trace label for this call (e.g. 'interviewer_turn').
    """
    if temperature is None:
        temperature = settings.generation_temperature
    async with observe_generation(
        operation,
        provider=settings.llm_provider,
        input={"system": system, "cache_prefix": cache_prefix, "messages": messages},
        metadata={"temperature": temperature},
    ) as gen:
        reply = await transport.call(
            "llm.generate",
            _generate_request(messages, system, cache_prefix, temperature),
            lambda: get_provider().generate(
                messages, system, cache_prefix=cache_prefix, temperature=temperature
            ),
        )
        gen.set_output(reply)
        return reply


def _generate_request(
    messages: list[dict],
    system: str,
    cache_prefix: str | None,
    temperature: float,
) -> dict:
    """The replay identity of a free-text generation.

    Shared by `generate` and `stream` so both produce the same hash: whether a
    reply was delivered in one piece or many is a property of the transport, not
    of what was asked for, and a cassette recorded either way must serve both.
    """
    return {
        "kind": "llm.generate",
        "provider": settings.llm_provider,
        "model": active_model(),
        "system": system,
        "cache_prefix": cache_prefix,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": settings.max_tokens,
    }


async def stream(
    messages: list[dict],
    system: str,
    *,
    cache_prefix: str | None = None,
    temperature: float | None = None,
    operation: str = "llm.stream",
) -> AsyncIterator[str]:
    """Generate a free-text reply, yielded incrementally.

    Same arguments and same resulting text as `generate` — only the delivery
    differs. Chunk boundaries are not meaningful and differ between live and
    replay; only the concatenation is defined.
    """
    if temperature is None:
        temperature = settings.generation_temperature
    chunks: list[str] = []
    async with observe_generation(
        operation,
        provider=settings.llm_provider,
        input={"system": system, "cache_prefix": cache_prefix, "messages": messages},
        metadata={"temperature": temperature, "streamed": True},
    ) as gen:
        stream_iter = transport.call_streaming(
            "llm.generate",
            _generate_request(messages, system, cache_prefix, temperature),
            lambda: get_provider().stream(
                messages, system, cache_prefix=cache_prefix, temperature=temperature
            ),
        )
        async for chunk in stream_iter:
            chunks.append(chunk)
            yield chunk
        gen.set_output("".join(chunks))


async def generate_structured(
    system: str,
    messages: list[dict],
    schema: dict,
    *,
    max_tokens: int = 400,
    temperature: float = 0.0,
    cache_prefix: str | None = None,
    operation: str = "llm.generate_structured",
    trace_metadata: dict | None = None,
) -> dict:
    """Generate a response constrained to a JSON-schema structured-output format.

    Defaults to `temperature=0` because callers (e.g. answer scoring) want a
    reproducible judgement, not a creative one: the same answer should score the
    same way across runs. `operation` is the trace label (e.g. 'score_answer').
    `trace_metadata` is extra key/values recorded on the trace only (e.g. the
    prompt and rubric versions) — it never enters the request bytes.
    """
    async with observe_generation(
        operation,
        provider=settings.llm_provider,
        input={"system": system, "cache_prefix": cache_prefix, "messages": messages},
        metadata={"temperature": temperature, "max_tokens": max_tokens, **(trace_metadata or {})},
    ) as gen:
        result = await transport.call(
            "llm.generate_structured",
            {
                "kind": "llm.generate_structured",
                "provider": settings.llm_provider,
                "model": active_model(),
                "system": system,
                "cache_prefix": cache_prefix,
                "messages": messages,
                "schema": schema,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            lambda: get_provider().generate_structured(
                system,
                messages,
                schema,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_prefix=cache_prefix,
            ),
        )
        gen.set_output(result)
        return result


async def parse(
    system: str,
    messages: list[dict],
    output_model: type[BaseModel],
    *,
    max_tokens: int = 500,
    operation: str = "llm.parse",
) -> BaseModel:
    """Parse a response into a validated Pydantic model via structured outputs.

    `operation` is the trace label (e.g. 'extract_profile', 'build_plan').
    """
    async with observe_generation(
        operation,
        provider=settings.llm_provider,
        input={"system": system, "messages": messages},
        metadata={"max_tokens": max_tokens, "output_model": output_model.__name__},
    ) as gen:
        parsed = await transport.call(
            "llm.parse",
            {
                "kind": "llm.parse",
                "provider": settings.llm_provider,
                "model": active_model(),
                "system": system,
                "messages": messages,
                "output_model": output_model.__name__,
                "output_schema": output_model.model_json_schema(),
                "max_tokens": max_tokens,
            },
            lambda: get_provider().parse(
                system, messages, output_model, max_tokens=max_tokens
            ),
            encode=lambda model: model.model_dump(mode="json"),
            decode=output_model.model_validate,
        )
        gen.set_output(parsed.model_dump() if isinstance(parsed, BaseModel) else parsed)
        return parsed
