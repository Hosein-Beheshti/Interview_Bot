"""Voyage AI embedding client.

Voyage is Anthropic's recommended embedding provider. We keep a thin async
wrapper so the rest of the codebase doesn't need to know the vendor.
"""
from __future__ import annotations

import asyncio
from typing import Literal

import voyageai

from config import settings

InputType = Literal["document", "query"]


class EmbeddingsClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise RuntimeError(
                "VOYAGE_API_KEY is not set — required for CV indexing"
            )
        self._client = voyageai.Client(api_key=api_key)
        self._model = model

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        if not texts:
            return []
        result = await asyncio.to_thread(
            self._client.embed,
            texts=texts,
            model=self._model,
            input_type=input_type,
        )
        return result.embeddings


_client: EmbeddingsClient | None = None


def get_client() -> EmbeddingsClient:
    global _client
    if _client is None:
        _client = EmbeddingsClient(
            api_key=settings.voyage_api_key,
            model=settings.embedding_model,
        )
    return _client
