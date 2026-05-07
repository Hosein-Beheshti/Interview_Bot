from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from services.stt import transcribe_audio
from services.tts import synthesize_speech

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        content_type = audio.content_type or "audio/webm"
        transcript = await transcribe_audio(audio_bytes, content_type)
        return {"transcript": transcript}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)}")


@router.post("/speak")
async def speak(request: SpeakRequest):
    try:
        audio_bytes = await synthesize_speech(request.text)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {str(e)}")
