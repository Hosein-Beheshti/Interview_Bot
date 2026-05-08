import asyncio
import websockets
from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel
from config import settings
from services.stt import transcribe_audio
from services.tts import synthesize_speech
from logger import logger

router = APIRouter()

DEEPGRAM_STREAM_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-3&smart_format=true&interim_results=true"
    "&endpointing=300&vad_events=true"
)


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


@router.websocket("/transcribe-stream")
async def transcribe_stream(client_ws: WebSocket):
    await client_ws.accept()

    if not settings.deepgram_api_key:
        await client_ws.close(code=1011, reason="Deepgram not configured")
        return

    try:
        async with websockets.connect(
            DEEPGRAM_STREAM_URL,
            additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
        ) as dg_ws:

            async def client_to_deepgram():
                try:
                    while True:
                        msg = await client_ws.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "bytes" in msg and msg["bytes"] is not None:
                            await dg_ws.send(msg["bytes"])
                        elif "text" in msg and msg["text"] is not None:
                            if msg["text"] == "close":
                                break
                except WebSocketDisconnect:
                    pass
                finally:
                    try:
                        await dg_ws.send('{"type":"CloseStream"}')
                    except Exception:
                        pass

            async def deepgram_to_client():
                try:
                    async for message in dg_ws:
                        if isinstance(message, bytes):
                            message = message.decode("utf-8", errors="ignore")
                        await client_ws.send_text(message)
                except Exception:
                    pass

            await asyncio.gather(client_to_deepgram(), deepgram_to_client())

    except Exception as e:
        logger.error(f"Deepgram stream error: {e}")
    finally:
        try:
            await client_ws.close()
        except Exception:
            pass
