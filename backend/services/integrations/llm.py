"""LLM facade.

The rest of the app imports `llm.generate`, `llm.generate_structured`, and
`llm.parse` — a stable, provider-agnostic seam. Each call delegates to whichever
backend `settings.llm_provider` selects (Claude, Gemini, …). Switching providers
is a config change: set LLM_PROVIDER and the matching API key; nothing here or
upstream changes. To add a backend, implement `LLMProvider` under
`services/integrations/providers/` and register it there.
"""
from __future__ import annotations

from pydantic import BaseModel

from config import settings

from .providers import get_provider


async def generate(
    messages: list[dict],
    system: str,
    *,
    cache_prefix: str | None = None,
    temperature: float | None = None,
) -> str:
    """Generate a free-text assistant reply.

    `cache_prefix` is turn-invariant system text (role guidance, the candidate's
    CV) that the provider may mark for prompt caching; `system` is the volatile
    remainder (this turn's instruction). When `cache_prefix` is None, `system` is
    sent as-is. `temperature` defaults to `settings.generation_temperature`.
    """
    if temperature is None:
        temperature = settings.generation_temperature
    return await get_provider().generate(
        messages, system, cache_prefix=cache_prefix, temperature=temperature
    )


async def generate_structured(
    system: str,
    messages: list[dict],
    schema: dict,
    *,
    max_tokens: int = 400,
    temperature: float = 0.0,
    cache_prefix: str | None = None,
) -> dict:
    """Generate a response constrained to a JSON-schema structured-output format.

    Defaults to `temperature=0` because callers (e.g. answer scoring) want a
    reproducible judgement, not a creative one: the same answer should score the
    same way across runs.
    """
    return await get_provider().generate_structured(
        system,
        messages,
        schema,
        max_tokens=max_tokens,
        temperature=temperature,
        cache_prefix=cache_prefix,
    )


async def parse(
    system: str,
    messages: list[dict],
    output_model: type[BaseModel],
    *,
    max_tokens: int = 500,
) -> BaseModel:
    """Parse a response into a validated Pydantic model via structured outputs."""
    return await get_provider().parse(
        system, messages, output_model, max_tokens=max_tokens
    )
