"""Anthropic (Claude) provider.

Wraps the Messages API: free-text generation, JSON-schema structured outputs, and
Pydantic-validated parsing. Uses Anthropic's native prompt caching for the
turn-invariant `cache_prefix`.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from interview_bot.config import settings
from interview_bot.telemetry import record_generation_usage

from .provider import LLMProvider, trim_to_context_limit

_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)

_RETRY = retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ValueError(
                "llm_provider='anthropic' but ANTHROPIC_API_KEY is not set."
            )
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )

    @_RETRY
    async def generate(
        self,
        messages: list[dict],
        system: str,
        *,
        model: str,
        cache_prefix: str | None = None,
        temperature: float | None = None,
    ) -> str:
        safe_messages = trim_to_context_limit(messages, (cache_prefix or "") + system)
        extra = {} if temperature is None else {"temperature": temperature}
        response = await self._client.messages.create(  # type: ignore[call-overload]  # SDK wants TypedDicts; plain dicts are valid at runtime
            model=model,
            max_tokens=settings.max_tokens,
            system=_system_param(cache_prefix, system),
            messages=safe_messages,
            **extra,
        )
        _record_usage(response)
        if not response.content or response.content[0].type != "text":
            raise ValueError(f"Unexpected response: stop_reason={response.stop_reason}")
        return response.content[0].text

    # Not decorated with @_RETRY: a stream that fails has already delivered part
    # of the reply, so re-running it would append a second attempt to the first.
    async def stream(
        self,
        messages: list[dict],
        system: str,
        *,
        model: str,
        cache_prefix: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        safe_messages = trim_to_context_limit(messages, (cache_prefix or "") + system)
        extra = {} if temperature is None else {"temperature": temperature}
        async with self._client.messages.stream(
            model=model,
            max_tokens=settings.max_tokens,
            system=_system_param(cache_prefix, system),
            messages=safe_messages,  # type: ignore[arg-type]  # SDK wants TypedDicts; plain dicts are valid at runtime
            **extra,  # type: ignore[arg-type]
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # Usage totals only exist once the stream is complete; reporting them
            # here keeps streamed turns visible to tracing and the spend ceiling.
            _record_usage(await stream.get_final_message())

    @_RETRY
    async def generate_structured(
        self,
        system: str,
        messages: list[dict],
        schema: dict,
        *,
        max_tokens: int = 400,
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> dict:
        response = await self._client.messages.create(  # type: ignore[call-overload]
            model=settings.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=_system_param(cache_prefix, system),
            output_config={"format": schema},
            messages=messages,
        )
        _record_usage(response)
        return _structured_json(response)

    @_RETRY
    async def parse(
        self,
        system: str,
        messages: list[dict],
        output_model: type[BaseModel],
        *,
        max_tokens: int = 500,
    ) -> BaseModel:
        response = await self._client.messages.parse(
            model=settings.model,
            max_tokens=max_tokens,
            system=system,
            output_format=output_model,
            messages=messages,  # type: ignore[arg-type]
        )
        _record_usage(response)
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(
                f"Structured parse returned no output: stop_reason={response.stop_reason}"
            )
        return parsed


def _record_usage(response) -> None:
    """Report token usage / request_id / stop_reason to the active trace.

    All-`getattr` so a shape change in the SDK degrades to partial metadata, never
    an error in the response path. `cache_*` tokens are surfaced separately so cost
    stays accurate under prompt caching.
    """
    usage = getattr(response, "usage", None)
    record_generation_usage(
        provider="anthropic",
        model=getattr(response, "model", settings.model),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
        request_id=getattr(response, "_request_id", None),
        stop_reason=getattr(response, "stop_reason", None),
    )


def _system_param(cache_prefix: str | None, system: str):
    """Build the `system` argument: a plain string, or cached-prefix + volatile
    blocks when a cache prefix is supplied."""
    if not cache_prefix:
        return system
    blocks = [
        {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}}
    ]
    if system:
        blocks.append({"type": "text", "text": system})
    return blocks


def _structured_json(response) -> dict:
    """Return the JSON object from a structured-output response, or raise."""
    block = next((b for b in response.content if b.type == "text"), None)
    if block is None:
        raise ValueError(
            f"No text block in structured response: stop_reason={response.stop_reason}"
        )
    return json.loads(block.text)
