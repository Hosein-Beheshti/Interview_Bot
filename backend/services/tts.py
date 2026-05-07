import httpx
from config import settings

DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"
DEFAULT_VOICE = "aura-2-thalia-en"


async def synthesize_speech(text: str) -> bytes:
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            DEEPGRAM_TTS_URL,
            params={"model": DEFAULT_VOICE},
            headers=headers,
            json={"text": text},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.content
