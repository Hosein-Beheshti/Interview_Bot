"""Google Gemini provider.

Wraps the google-genai SDK to the same three-method contract as the Anthropic
provider. A free API key works here: https://aistudio.google.com/apikey.

Two shape differences from Anthropic are handled internally:
  - Roles: Gemini calls the assistant turn "model" (not "assistant"), and the
    system prompt is a separate `system_instruction`, not a message.
  - Structured outputs: Gemini's `response_schema` is a stricter OpenAPI subset —
    it rejects `additionalProperties` and only honors `enum` on string fields — so
    the canonical JSON schema is translated by `_to_gemini_schema`.

Gemini has no explicit per-request prompt-cache control like Anthropic's, so
`cache_prefix` is simply folded into the system instruction (newer models cache
long prompt prefixes implicitly).
"""
from __future__ import annotations

import json

from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from config import settings

from .base import LLMProvider, trim_to_context_limit

# Retry transient failures: 5xx server errors and 429 rate limits.
_RETRY_STATUS = {429, 500, 503}


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, errors.APIError) and getattr(exc, "code", None) in _RETRY_STATUS


_RETRY = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise ValueError(
                "llm_provider='gemini' but GEMINI_API_KEY is not set. "
                "Get a free key at https://aistudio.google.com/apikey."
            )
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @_RETRY
    async def generate(
        self,
        messages: list[dict],
        system: str,
        *,
        cache_prefix: str | None = None,
        temperature: float | None = None,
    ) -> str:
        full_system = _merge_system(cache_prefix, system)
        safe_messages = trim_to_context_limit(messages, full_system)
        response = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=_to_contents(safe_messages),
            config=types.GenerateContentConfig(
                system_instruction=full_system or None,
                max_output_tokens=settings.max_tokens,
                temperature=temperature,
                thinking_config=_thinking_config(),
            ),
        )
        text = response.text
        if not text:
            raise ValueError("Empty response from Gemini")
        return text

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
        response = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=_to_contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=_merge_system(cache_prefix, system) or None,
                max_output_tokens=max_tokens,
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=_to_gemini_schema(schema),
                thinking_config=_thinking_config(),
            ),
        )
        if not response.text:
            raise ValueError("Empty structured response from Gemini")
        return json.loads(response.text)

    @_RETRY
    async def parse(
        self,
        system: str,
        messages: list[dict],
        output_model: type[BaseModel],
        *,
        max_tokens: int = 500,
    ) -> BaseModel:
        response = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=_to_contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=system or None,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                response_schema=output_model,
                thinking_config=_thinking_config(),
            ),
        )
        parsed = response.parsed
        if parsed is None:
            raise ValueError("Structured parse returned no output from Gemini")
        return parsed


def _thinking_config() -> types.ThinkingConfig:
    """Per-request thinking budget (see `settings.gemini_thinking_budget`).

    Disabled (0) by default so the bounded `max_output_tokens` is spent on the
    answer/JSON rather than on hidden reasoning that can truncate the output.
    """
    return types.ThinkingConfig(thinking_budget=settings.gemini_thinking_budget)


def _merge_system(cache_prefix: str | None, system: str) -> str:
    """Fold the (uncached) prefix into the system instruction."""
    return "\n\n".join(p for p in (cache_prefix, system) if p)


def _to_contents(messages: list[dict]) -> list[dict]:
    """Translate Anthropic-style messages to Gemini `contents`.

    The assistant role is named "model" in Gemini, and content is a list of parts.
    """
    return [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]


def _to_gemini_schema(schema: dict) -> dict:
    """Translate the canonical JSON schema to Gemini's OpenAPI subset.

    Unwraps the `{"type": "json_schema", "schema": ...}` envelope, strips keys
    Gemini rejects (`additionalProperties`), and rewrites integer `enum`s — which
    Gemini only supports on strings — as a plain integer with the allowed values
    moved into the description, so the constraint survives as a hint.
    """
    inner = schema.get("schema", schema) if schema.get("type") == "json_schema" else schema
    return _clean_node(inner)


def _clean_node(node):
    if isinstance(node, list):
        return [_clean_node(n) for n in node]
    if not isinstance(node, dict):
        return node

    out = {k: v for k, v in node.items() if k not in ("additionalProperties", "$schema", "title")}

    if out.get("type") == "integer" and "enum" in out:
        allowed = out.pop("enum")
        desc = out.get("description", "")
        out["description"] = (f"{desc} " if desc else "") + f"Allowed values: {allowed}."

    for key in ("properties",):
        if key in out and isinstance(out[key], dict):
            out[key] = {k: _clean_node(v) for k, v in out[key].items()}
    if "items" in out:
        out["items"] = _clean_node(out["items"])

    return out
