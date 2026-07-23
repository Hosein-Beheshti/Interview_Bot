from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from interview_bot.integrations import speech

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        content_type = audio.content_type or "audio/webm"
        transcript = await speech.transcribe(audio_bytes, content_type)
        return {"transcript": transcript}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)}") from e


@router.post("/speak")
async def speak(request: SpeakRequest):
    try:
        audio_bytes = await speech.synthesize(request.text)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {str(e)}") from e
