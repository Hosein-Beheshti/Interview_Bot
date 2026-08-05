"""Speech transport adapter (Deepgram): speech-to-text and text-to-speech.

Swapping speech providers means rewriting this module's internals; `transcribe()`
and `synthesize()` are the seam the rest of the app depends on. A single shared
async client is reused across calls.
"""
from __future__ import annotations

import base64
import hashlib

import httpx

from interview_bot.config import settings
from interview_bot.llm import transport
from interview_bot.telemetry import observe_span

# Vendor-specific selections — the only Deepgram-isms in the app. Swapping
# providers means changing these and the request shapes below; nothing outside
# this module references them.
_STT_URL = "https://api.deepgram.com/v1/listen"   # speech-to-text endpoint
_TTS_URL = "https://api.deepgram.com/v1/speak"    # text-to-speech endpoint
_STT_MODEL = "nova-3"                             # Deepgram STT model
_TTS_VOICE = "aura-2-thalia-en"                   # Deepgram Aura-2 voice

# Content types a browser MediaRecorder or a normal audio file upload actually
# produces. Audio has no reliable filename to key off (unlike CV uploads), so
# this checks Content-Type instead.
SUPPORTED_CONTENT_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/mpeg",
    "audio/m4a",
    "audio/x-m4a",
}

_client: httpx.AsyncClient | None = None


def is_supported_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";")[0].strip().lower() in SUPPORTED_CONTENT_TYPES


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
    async def _live() -> str:
        response = await _get_client().post(
            _STT_URL,
            params={"model": _STT_MODEL, "smart_format": "true"},
            headers=_auth_headers(content_type),
            content=audio,
        )
        response.raise_for_status()
        data = response.json()
        return data["results"]["channels"][0]["alternatives"][0]["transcript"]

    async with observe_span(
        "deepgram.stt",
        input={"bytes": len(audio), "content_type": content_type},
        metadata={"model": _STT_MODEL},
    ):
        # Audio is identified by hash, not embedded, so cassettes stay small.
        return await transport.call(
            "speech.transcribe",
            {
                "kind": "speech.transcribe",
                "provider": "deepgram",
                "model": _STT_MODEL,
                "content_type": content_type,
                "audio_sha256": hashlib.sha256(audio).hexdigest(),
            },
            _live,
        )


async def synthesize(text: str) -> bytes:
    """Synthesize text to speech audio (text-to-speech)."""
    async def _live() -> bytes:
        response = await _get_client().post(
            _TTS_URL,
            params={"model": _TTS_VOICE},
            headers=_auth_headers("application/json"),
            json={"text": text},
        )
        response.raise_for_status()
        return response.content

    async with observe_span(
        "deepgram.tts",
        input={"chars": len(text)},
        metadata={"voice": _TTS_VOICE},
    ):
        return await transport.call(
            "speech.synthesize",
            {
                "kind": "speech.synthesize",
                "provider": "deepgram",
                "voice": _TTS_VOICE,
                "text": text,
            },
            _live,
            encode=lambda audio: base64.b64encode(audio).decode("ascii"),
            decode=base64.b64decode,
        )
