"""Speech-to-text and text-to-speech endpoints.

Both wrap a third-party vendor (Deepgram). Vendor failures are logged with their
detail and reported to the caller as a bare 502: an upstream error body can carry
request ids, quota figures, or fragments of our own request, and these endpoints
are reachable by anyone.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from interview_bot.api import limits
from interview_bot.config import settings
from interview_bot.integrations import speech
from interview_bot.logger import logger

router = APIRouter(tags=["voice"])


class SpeakRequest(BaseModel):
    # Bounded so the endpoint cannot be driven as an open-ended text-to-speech
    # service; one interviewer question is far below this.
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/transcribe", dependencies=[Depends(limits.enforce(limits.TRANSCRIPTION))])
async def transcribe(audio: UploadFile = File(...)) -> dict[str, str]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio_bytes) > settings.audio_max_bytes:
        limit_mb = settings.audio_max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Audio exceeds {limit_mb}MB limit")
    if not speech.is_supported_content_type(audio.content_type):
        raise HTTPException(status_code=415, detail="Unsupported audio type.")

    try:
        transcript = await speech.transcribe(audio_bytes, audio.content_type or "audio/webm")
    except Exception as e:
        logger.error(f"Transcription failed | bytes={len(audio_bytes)} | error={e}")
        raise HTTPException(status_code=502, detail="Transcription unavailable") from e
    return {"transcript": transcript}


@router.post("/speak")
async def speak(request: SpeakRequest, http_request: Request) -> Response:
    # Charged per character, not per call: synthesis is billed by length, so a
    # handful of maximum-length requests costs the same as many short ones.
    limits.charge(
        limits.TTS_CHARACTERS, limits.client_ip(http_request), amount=len(request.text)
    )
    try:
        audio_bytes = await speech.synthesize(request.text)
    except Exception as e:
        logger.error(f"Speech synthesis failed | chars={len(request.text)} | error={e}")
        raise HTTPException(status_code=502, detail="Speech synthesis unavailable") from e
    return Response(content=audio_bytes, media_type="audio/mpeg")
