"""
backend/services/wake_word.py — Continuous wake-word listener
Runs in background, fires callback when "jarvis" detected.

Strategy:
  - Capture short rolling audio windows (3s)
  - Transcribe each with Whisper
  - Check for wake phrase
  - Fire callback → voice pipeline takes over

This is lightweight: small Whisper on 3s audio ~300ms on CPU.
"""

import asyncio
import logging
import time
from typing import Callable, Optional

from config import settings
from services.voice_stt import stt_service

log = logging.getLogger("jarvis.wake")

WINDOW_SECS   = 3.0    # extended from 2s — gives full time for accented pronunciation
COOLDOWN_SECS = 5.0    # min seconds between wake detections (prevents double-fire)


class WakeWordDetector:

    def __init__(self):
        self._running    = False
        self._task: Optional[asyncio.Task] = None
        self._callback: Optional[Callable] = None
        self._last_wake  = 0.0
        self._busy       = False   # True while on_wake pipeline is running

    async def start(self, on_wake: Callable):
        """Begin continuous listening for wake word."""
        if not settings.voice.enabled:
            log.info("Wake word detection disabled in config")
            return
        if self._running:
            return
        self._callback = on_wake
        self._running  = True
        self._task     = asyncio.create_task(self._listen_loop())
        log.info(f"Wake word active: '{settings.voice.wake_word}' (say it to activate)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Wake word detector stopped")

    def set_busy(self, busy: bool):
        """Pause/resume wake detection while the voice pipeline is handling a command."""
        self._busy = busy
        if busy:
            log.debug("Wake detector paused — pipeline active")
        else:
            log.debug("Wake detector resumed")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Main loop ─────────────────────────────────────────────────
    async def _listen_loop(self):
        """Capture short windows, check for wake word."""
        while self._running:
            try:
                # Yield while the command pipeline is running — avoids stt_service conflicts
                if self._busy:
                    await asyncio.sleep(0.2)
                    continue

                # Capture 3s window
                await stt_service.start()
                await asyncio.sleep(WINDOW_SECS)
                result = await stt_service.stop()
                transcript = result.get("transcript", "").strip()

                if transcript:
                    log.debug(f"Wake window: {transcript!r}")

                if transcript and stt_service.check_wake_word(transcript):
                    now = time.monotonic()
                    if now - self._last_wake > COOLDOWN_SECS:
                        self._last_wake = now
                        log.info(f"Wake word detected: {transcript!r}")
                        if self._callback:
                            asyncio.create_task(self._callback(transcript))

                # Small gap between windows
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Wake loop error: {e}")
                await asyncio.sleep(1.0)


# Singleton
wake_detector = WakeWordDetector()
