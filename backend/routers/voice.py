"""
backend/routers/voice.py — Voice STT/TTS endpoints + WebSocket pipeline
"""

import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from config import settings
from services.voice_stt import stt_service
from services.voice_tts import tts_service
from services.wake_word import wake_detector

log = logging.getLogger("jarvis.voice")
router = APIRouter()


class TTSRequest(BaseModel):
    text:  str
    voice: str = "en_US-lessac-medium"

class SpeakRequest(BaseModel):
    text:     str
    priority: bool = False


# ── STT ──────────────────────────────────────────────────────
@router.post("/start")
async def start_listening():
    if stt_service.is_listening:
        return {"status": "already_listening"}
    await stt_service.start()
    return {"status": "listening"}


@router.post("/stop")
async def stop_listening():
    result = await stt_service.stop()
    return {"status": "stopped", **result}


@router.get("/status")
async def voice_status():
    return {
        "listening":     stt_service.is_listening,
        "speaking":      tts_service.is_speaking,
        "wake_active":   wake_detector.is_running,
        "wake_enabled":  settings.voice.enabled,
        "wake_word":     settings.voice.wake_word,
    }


# ── TTS ──────────────────────────────────────────────────────
@router.post("/speak")
async def speak(req: SpeakRequest):
    """Queue text for TTS playback."""
    await tts_service.speak(req.text, priority=req.priority)
    return {"status": "queued", "text": req.text[:80]}


@router.post("/tts")
async def synthesize(req: TTSRequest):
    """Synthesize to audio file, return path."""
    try:
        path = await tts_service.synthesize(req.text, voice=req.voice)
        return {"status": "ok", "audio_path": str(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Wake word ────────────────────────────────────────────────
@router.post("/wake/start")
async def start_wake():
    """Start background wake-word listener."""
    if not settings.voice.enabled:
        return {"status": "disabled", "message": "Wake word detection is disabled in config"}

    async def on_wake(transcript: str):
        log.info(f"Wake callback: {transcript!r}")
    await wake_detector.start(on_wake)
    return {"status": "wake_listening"}


@router.post("/wake/stop")
async def stop_wake():
    await wake_detector.stop()
    return {"status": "wake_stopped"}


# ── Full pipeline WebSocket ──────────────────────────────────
@router.websocket("/ws")
async def voice_ws(ws: WebSocket):
    """
    Real-time voice pipeline.
    Client sends: {"type": "start"} | {"type": "stop"} | {"type": "ping"}
    Server sends: listening | transcript | response | error | pong events
    """
    await ws.accept()
    log.info("Voice WS connected")

    async def send(data: dict):
        try:
            await ws.send_json(data)
        except Exception:
            pass

    try:
        while True:
            raw  = await ws.receive_text()
            data = json.loads(raw)
            t    = data.get("type")

            if t == "start":
                await stt_service.start()
                await send({"type": "listening"})

            elif t == "stop":
                await send({"type": "processing"})
                result     = await stt_service.stop()
                transcript = result.get("transcript", "").strip()

                if not transcript:
                    await send({"type": "empty"})
                    continue

                await send({"type": "transcript", "text": transcript})

                # Check wake word (optional gating)
                if data.get("check_wake") and not stt_service.check_wake_word(transcript):
                    await send({"type": "no_wake"})
                    continue

                # Route through AI
                from services.router_engine import router_engine
                ai = await router_engine.route(transcript)
                await send({
                    "type":      "response",
                    "text":      ai["response"],
                    "model":     ai["model"],
                    "task_type": ai["task_type"],
                })

                # Speak response
                await tts_service.speak(ai["response"], priority=True)
                await send({"type": "speaking"})

            elif t == "speak":
                text = data.get("text", "")
                if text:
                    await tts_service.speak(text)
                    await send({"type": "speaking", "text": text[:80]})

            elif t == "ping":
                await send({"type": "pong"})

    except WebSocketDisconnect:
        log.info("Voice WS disconnected")
        await stt_service.stop()
    except Exception as e:
        log.error(f"Voice WS error: {e}")
        await send({"type": "error", "message": str(e)})
