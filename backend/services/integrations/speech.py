"""Speech transport adapter (Deepgram): speech-to-text and text-to-speech.

Swapping speech providers means rewriting this module's internals; `transcribe()`
and `synthesize()` are the seam the rest of the app depends on. A single shared
async client is reused across calls.
"""
from __future__ import annotations

import httpx

from config import settings
from services.observability import observe_span

# Vendor-specific selections — the only Deepgram-isms in the app. Swapping
# providers means changing these and the request shapes below; nothing outside
# this module references them.
_STT_URL = "https://api.deepgram.com/v1/listen"   # speech-to-text endpoint
_TTS_URL = "https://api.deepgram.com/v1/speak"    # text-to-speech endpoint
_STT_MODEL = "nova-3"                             # Deepgram STT model
_TTS_VOICE = "aura-2-thalia-en"                   # Deepgram Aura-2 voice

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


def _auth_headers(content_type: str) -> dict[str, str]:
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set — required for voice features")
    return {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": content_type,
    }


async def transcribe(audio: bytes, content_type: str = "audio/webm") -> str:
    """Transcribe audio bytes to text (speech-to-text)."""
    async with observe_span(
        "deepgram.stt",
        input={"bytes": len(audio), "content_type": content_type},
        metadata={"model": _STT_MODEL},
    ):
        response = await _get_client().post(
            _STT_URL,
            params={"model": _STT_MODEL, "smart_format": "true"},
            headers=_auth_headers(content_type),
            content=audio,
        )
        response.raise_for_status()
        data = response.json()
    return data["results"]["channels"][0]["alternatives"][0]["transcript"]


async def synthesize(text: str) -> bytes:
    """Synthesize text to speech audio (text-to-speech)."""
    async with observe_span(
        "deepgram.tts",
        input={"chars": len(text)},
        metadata={"voice": _TTS_VOICE},
    ):
        response = await _get_client().post(
            _TTS_URL,
            params={"model": _TTS_VOICE},
            headers=_auth_headers("application/json"),
            json={"text": text},
        )
        response.raise_for_status()
    return response.content
