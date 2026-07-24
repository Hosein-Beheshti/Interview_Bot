"""The LLM provider seam.

Every backend (Claude, Gemini, …) implements `LLMProvider`. The rest of the app
only ever calls the three methods declared here, so swapping providers is a
config change, never a code change. See `interview_bot.llm` (the facade) for the
facade the app actually imports.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel

from interview_bot.config import settings
from interview_bot.logger import logger


def trim_to_context_limit(messages: list[dict], system: str) -> list[dict]:
    """Drop oldest messages when total input chars approach the context limit.

    Provider-agnostic: budgeting is by character count, not tokens, so it holds
    regardless of which model's tokenizer is behind the seam.
    """
    trimmed = list(messages)
    total = sum(len(m["content"]) for m in trimmed) + len(system)
    while total > settings.max_context_chars and len(trimmed) > 1:
        removed = trimmed.pop(0)
        total -= len(removed["content"])
        logger.warning("Context limit: dropped oldest message to fit within budget")
    return trimmed


class LLMProvider(ABC):
    """Domain-agnostic transport for a chat LLM.

    `cache_prefix`, where supported, is turn-invariant system text (role guidance,
    the candidate's CV) that a provider may mark for prompt caching so re-sending
    it every turn is nearly free; `system` is the volatile remainder. Providers
    without a caching API simply fold the prefix into the system instruction.
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        system: str,
        *,
        cache_prefix: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Generate a free-text assistant reply.

        `temperature` is the sampling temperature; when None the provider uses its
        own default (the API default).
        """

    @abstractmethod
    def stream(
        self,
        messages: list[dict],
        system: str,
        *,
        cache_prefix: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Generate the same reply as `generate`, yielded incrementally.

        The concatenation of every chunk must equal what `generate` would have
        returned for the same arguments — streaming is a delivery detail, not a
        different request, and the record/replay waist relies on that being true.

        Unlike the other methods this one is not retried: by the time a stream
        fails, part of the reply has already been handed to the caller, so a
        transparent retry would duplicate text rather than replace it.
        """

    @abstractmethod
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
        """Generate a response constrained to a JSON-schema structured output.

        `schema` is the canonical `{"type": "json_schema", "schema": {...}}` shape;
        each provider translates it to its own structured-output API.
        """

    @abstractmethod
    async def parse(
        self,
        system: str,
        messages: list[dict],
        output_model: type[BaseModel],
        *,
        max_tokens: int = 500,
    ) -> BaseModel:
        """Parse a response into a validated Pydantic model."""
