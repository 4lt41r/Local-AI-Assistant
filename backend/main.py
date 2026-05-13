"""
backend/main.py — JARVIS FastAPI Backend
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import chat, models, voice, system, vscode, config as cfg_router
from routers import routing, tools as tools_router
from services.ollama_manager import ollama_manager
from services.model_manager import model_manager
from services.wake_word import wake_detector
from services.voice_tts import tts_service
from services.memory_service import memory_service
from services.activity_log import log_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("jarvis")

# Phrases that end a voice conversation
_GOODBYE_WORDS = {
    "bye", "goodbye", "good bye", "stop", "that's all", "that is all",
    "never mind", "nevermind", "dismiss", "exit", "quit", "sleep",
}


def _is_goodbye(text: str) -> bool:
    lowered = text.lower().strip()
    return any(w in lowered for w in _GOODBYE_WORDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("JARVIS backend starting...")
    await ollama_manager.start()
    await model_manager.start()
    await tts_service.start()

    async def on_wake(transcript: str):
        """
        Continuous voice conversation triggered by wake word.
        Stays in a listen/respond loop until the user says goodbye
        or 10 turns pass without input.
        """
        log.info(f"Wake word detected: {transcript!r}")
        log_event("voice", "Wake word detected", transcript or "jarvis")
        wake_detector.set_busy(True)

        # Write to the shared "default" session so voice turns show up in chat history
        session_id = "default"

        try:
            from services.voice_stt import stt_service
            from services.router_engine import router_engine

            await tts_service.speak("Yes?", priority=True)
            await tts_service.wait_until_done()
            await asyncio.sleep(0.3)    # brief silence before mic opens

            consecutive_empty = 0

            for turn in range(10):      # max 10 back-and-forth turns
                log.info(f"Voice conversation turn {turn + 1} — listening...")
                await stt_service.start()
                await asyncio.sleep(8)  # 8 s window for accented/slower speech
                result  = await stt_service.stop()
                command = result.get("transcript", "").strip()

                if not command:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        # Two empty windows in a row — user probably stopped talking
                        break
                    await tts_service.speak("I'm still listening.", priority=True)
                    await tts_service.wait_until_done()
                    await asyncio.sleep(0.3)
                    continue

                consecutive_empty = 0

                if _is_goodbye(command):
                    await tts_service.speak(
                        "Alright, let me know if you need anything.", priority=True
                    )
                    await tts_service.wait_until_done()
                    break

                log.info(f"Voice turn {turn + 1} command: {command!r}")
                log_event("voice", f"Heard: {command[:70]}")

                # Fetch history and user profile context for the model
                history      = memory_service.get_history(session_id)
                user_context = memory_service.get_system_context()

                ai = await router_engine.route_with_tools(
                    command,
                    history=history,
                    user_context=user_context,
                )
                response = ai.get("response", "")
                log.info(f"AI response: {response[:80]!r}")
                log_event("ai", f"JARVIS: {response[:70]}")

                # Persist both sides
                memory_service.add_turn(session_id, "user",      command)
                memory_service.add_turn(session_id, "assistant", response)

                await tts_service.speak(response, priority=True)
                await tts_service.wait_until_done()
                await asyncio.sleep(0.5)    # brief pause so user knows response ended

        except Exception as e:
            log.error(f"Wake pipeline error: {e}")
        finally:
            wake_detector.set_busy(False)

    if settings.voice.enabled:
        await wake_detector.start(on_wake)
    else:
        log.info("Wake word detection is disabled by config")
    log.info(f"Backend ready on port {settings.backend_port}")
    yield

    # Shutdown
    log.info("JARVIS backend shutting down...")
    await wake_detector.stop()
    await tts_service.stop()
    await model_manager.stop()
    await ollama_manager.stop()


app = FastAPI(title="JARVIS Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router,          prefix="")
app.include_router(models.router,        prefix="/models")
app.include_router(routing.router,       prefix="/routing")
app.include_router(voice.router,         prefix="/voice")
app.include_router(system.router,        prefix="/system")
app.include_router(vscode.router,        prefix="/vscode")
app.include_router(cfg_router.router,    prefix="")
app.include_router(tools_router.router,  prefix="")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
