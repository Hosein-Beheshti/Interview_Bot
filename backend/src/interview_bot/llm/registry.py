"""Provider registry and factory.

To add a provider: implement `LLMProvider` in a new module here and register its
class in `_PROVIDERS` under a key. Selection is driven by `settings.llm_provider`.
Constructors are imported lazily so that, e.g., a Gemini-only deployment never
imports the Anthropic SDK (and vice versa).
"""
from __future__ import annotations

from functools import cache

from interview_bot.config import settings

from .provider import LLMProvider


def _make_anthropic() -> LLMProvider:
    from .anthropic import AnthropicProvider

    return AnthropicProvider()


def _make_gemini() -> LLMProvider:
    from .gemini import GeminiProvider

    return GeminiProvider()


_PROVIDERS = {
    "anthropic": _make_anthropic,
    "gemini": _make_gemini,
}


@cache
def get_provider() -> LLMProvider:
    """Return the configured provider singleton (built once, then cached)."""
    try:
        factory = _PROVIDERS[settings.llm_provider]
    except KeyError:
        raise ValueError(
            f"Unknown llm_provider={settings.llm_provider!r}. "
            f"Available: {', '.join(sorted(_PROVIDERS))}."
        ) from None
    return factory()


__all__ = ["LLMProvider", "get_provider"]
