"""Embedding transport adapter (Voyage AI).

A thin wrapper exposing `embed()`. Swapping embedding providers means rewriting
this module's internals; the function signature is the seam the rest of the app
depends on.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from config import settings
from services.observability import observe_span

InputType = Literal["document", "query"]

# Created lazily so importing this module (and anything that transitively imports
# it) does not require the voyageai SDK or a configured key until embeddings are
# actually used.
_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.voyage_api_key:
            raise RuntimeError("VOYAGE_API_KEY is not set — required for CV indexing")
        import voyageai

        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


async def embed(texts: list[str], input_type: InputType) -> list[list[float]]:
    """Embed `texts` for either storage ('document') or search ('query')."""
    if not texts:
        return []
    async with observe_span(
        "voyage.embed",
        input={"count": len(texts), "input_type": input_type},
        metadata={"model": settings.embedding_model},
    ):
        result = await asyncio.to_thread(
            _get_client().embed,
            texts=texts,
            model=settings.embedding_model,
            input_type=input_type,
        )
    return result.embeddings
