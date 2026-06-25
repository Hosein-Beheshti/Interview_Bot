"""Anthropic (Claude) provider.

Wraps the Messages API: free-text generation, JSON-schema structured outputs, and
Pydantic-validated parsing. Uses Anthropic's native prompt caching for the
turn-invariant `cache_prefix`.
"""
from __future__ import annotations

import json

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

from .base import LLMProvider, trim_to_context_limit

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
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    @_RETRY
    async def generate(
        self,
        messages: list[dict],
        system: str,
        *,
        cache_prefix: str | None = None,
        temperature: float | None = None,
    ) -> str:
        safe_messages = trim_to_context_limit(messages, (cache_prefix or "") + system)
        extra = {} if temperature is None else {"temperature": temperature}
        response = await self._client.messages.create(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=_system_param(cache_prefix, system),
            messages=safe_messages,
            **extra,
        )
        if not response.content or response.content[0].type != "text":
            raise ValueError(f"Unexpected response: stop_reason={response.stop_reason}")
        return response.content[0].text

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
        response = await self._client.messages.create(
            model=settings.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=_system_param(cache_prefix, system),
            output_config={"format": schema},
            messages=messages,
        )
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
            messages=messages,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(
                f"Structured parse returned no output: stop_reason={response.stop_reason}"
            )
        return parsed


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
