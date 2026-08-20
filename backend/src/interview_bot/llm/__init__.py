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
    """The configured provider's default model — scoring, judging, extraction."""
    return settings.gemini_model if settings.llm_provider == "gemini" else settings.model


def generation_model() -> str:
    """The model used for interviewer turn generation.

    `settings.generator_model` when set, otherwise the provider default — so a
    stronger model can phrase the interview while the schema-constrained calls
    stay on the cheaper one. It must be a model name the *active* provider
    understands; this is one override, not one per provider.
    """
    return settings.generator_model or active_model()


def judge_model() -> str:
    """The model used to judge generated turns.

    `settings.judge_model` when set, otherwise the provider default. Judging is
    eval-only, so this never affects a live interview — it exists so the judge can
    be pinned to a stronger model than the generator it grades. See the
    `judge_model` note in `config.py` for why sharing one is a measurement problem
    and not just a cost one.
    """
    return settings.judge_model or active_model()


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
                messages,
                system,
                model=generation_model(),
                cache_prefix=cache_prefix,
                temperature=temperature,
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
        "model": generation_model(),
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
                messages,
                system,
                model=generation_model(),
                cache_prefix=cache_prefix,
                temperature=temperature,
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
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    cache_prefix: str | None = None,
    operation: str = "llm.generate_structured",
    trace_metadata: dict | None = None,
) -> dict:
    """Generate a response constrained to a JSON-schema structured-output format.

    Defaults to `temperature=0` because callers (e.g. answer scoring) want a
    reproducible judgement, not a creative one: the same answer should score the
    same way across runs. `max_tokens` defaults to
    `settings.structured_max_tokens`. `operation` is the trace label (e.g.
    'score_answer'). `trace_metadata` is extra key/values recorded on the trace
    only (e.g. the prompt and rubric versions) — it never enters the request bytes.
    """
    if max_tokens is None:
        max_tokens = settings.structured_max_tokens
    # Defaulted here rather than in the signature so the resolved name reaches
    # both the replay identity and the provider — a model read inside the adapter
    # would be absent from the cassette that is supposed to pin it.
    model = model or active_model()
    async with observe_generation(
        operation,
        provider=settings.llm_provider,
        input={"system": system, "cache_prefix": cache_prefix, "messages": messages},
        metadata={
            "temperature": temperature,
            "max_tokens": max_tokens,
            "model": model,
            **(trace_metadata or {}),
        },
    ) as gen:
        result = await transport.call(
            "llm.generate_structured",
            {
                "kind": "llm.generate_structured",
                "provider": settings.llm_provider,
                "model": model,
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
                model=model,
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
    max_tokens: int | None = None,
    operation: str = "llm.parse",
) -> BaseModel:
    """Parse a response into a validated Pydantic model via structured outputs.

    `max_tokens` defaults to `settings.parse_max_tokens`. `operation` is the trace
    label (e.g. 'extract_profile', 'build_plan').
    """
    if max_tokens is None:
        max_tokens = settings.parse_max_tokens
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
