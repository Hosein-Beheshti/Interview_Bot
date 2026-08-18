"""Speech-to-text and text-to-speech endpoints.

Both wrap a third-party vendor (Deepgram). Vendor failures are logged with their
detail and reported to the caller as a bare 502: an upstream error body can carry
request ids, quota figures, or fragments of our own request, and these endpoints
are reachable by anyone.

Both spend vendor money per call, so both require a signed-in user. Without that,
`/speak` is an open text-to-speech proxy for anyone who can reach the URL and
`/transcribe` an open transcription one — the per-IP quotas alone only bound how
fast a single address can spend, not who is allowed to.

`/transcribe` also debits credits per call. `/speak` does not: one reply is
synthesized as several requests as it streams, so charging per request would
price the same reply differently depending on how the client happened to chunk
it — a rendering detail deciding the bill. A session asks for a bounded number of
questions, so the synthesis it implies is bounded too and is paid for once, in
`interview_session_credit_cost`. What remains uncharged is a signed-in caller
calling `/speak` directly without a session; `TTS_CHARACTERS` caps that per
address per day.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from interview_bot.api import credits, limits
from interview_bot.api.auth import get_current_user
from interview_bot.config import settings
from interview_bot.integrations import speech
from interview_bot.logger import logger
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import User

router = APIRouter(tags=["voice"])


class SpeakRequest(BaseModel):
    # Bounded so the endpoint cannot be driven as an open-ended text-to-speech
    # service; one interviewer question is far below this.
    text: str = Field(..., min_length=1, max_length=settings.tts_text_max_chars)


@router.post("/transcribe", dependencies=[Depends(limits.enforce(limits.TRANSCRIPTION))])
async def transcribe(
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    audio_bytes = await audio.read()
    # Validate before charging: a malformed upload never reaches the vendor, so
    # it must not cost the caller anything.
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio_bytes) > settings.audio_max_bytes:
        limit_mb = settings.audio_max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Audio exceeds {limit_mb}MB limit")
    if not speech.is_supported_content_type(audio.content_type):
        raise HTTPException(status_code=415, detail="Unsupported audio type.")

    with credits.charged(db, user.id, settings.transcription_credit_cost):
        try:
            transcript = await speech.transcribe(audio_bytes, audio.content_type or "audio/webm")
        except Exception as e:
            logger.error(f"Transcription failed | bytes={len(audio_bytes)} | error={e}")
            raise HTTPException(status_code=502, detail="Transcription unavailable") from e
    return {"transcript": transcript}


@router.post("/speak")
async def speak(
    request: SpeakRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
) -> Response:
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
