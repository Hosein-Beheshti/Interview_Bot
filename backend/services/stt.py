import httpx
from config import settings

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


async def transcribe_audio(audio_bytes: bytes, content_type: str = "audio/webm") -> str:
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": content_type,
    }
    params = {"model": "nova-3", "smart_format": "true"}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            DEEPGRAM_URL,
            params=params,
            headers=headers,
            content=audio_bytes,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["results"]["channels"][0]["alternatives"][0]["transcript"]
