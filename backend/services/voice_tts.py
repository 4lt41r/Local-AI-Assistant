"""
backend/services/voice_tts.py — TTS service
Primary: edge-tts (Microsoft neural voices, excellent quality)
Fallback: pyttsx3 (Windows SAPI5, always available)
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

from config import INSTALL_ROOT, settings

log = logging.getLogger("jarvis.tts")

TTS_OUT_WAV = INSTALL_ROOT / "logs" / "tts_output.wav"
TTS_OUT_MP3 = INSTALL_ROOT / "logs" / "tts_output.mp3"
PIPER_DIR = INSTALL_ROOT / "voice" / "piper"

# Edge TTS voice — clear neutral English, easy to understand
# Full list: run `edge-tts --list-voices` to see all options
EDGE_VOICE = "en-US-GuyNeural"   # clear male voice


class TTSService:

    def __init__(self):
        self._queue: asyncio.Queue      = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._speaking   = False
        self._engine     = None
        self._backend    = self._detect_backend()

    def _detect_backend(self) -> str:
        if self._piper_available():
            log.info("TTS backend: piper (local)")
            return "piper"
        try:
            import edge_tts
            log.info("TTS backend: edge-tts (Microsoft neural)")
            return "edge_tts"
        except ImportError:
            pass
        try:
            import pyttsx3
            log.info("TTS backend: pyttsx3 (Windows SAPI5)")
            return "pyttsx3"
        except ImportError:
            pass
        log.warning("No TTS backend. Run: pip install edge-tts")
        return "none"

    def _piper_available(self) -> bool:
        exe = PIPER_DIR / "piper.exe"
        voice_name = settings.voice.piper_voice or "en_US-lessac-medium"
        model_file = PIPER_DIR / f"{voice_name}.onnx"
        config_file = PIPER_DIR / f"{voice_name}.onnx.json"
        if exe.exists() and model_file.exists() and config_file.exists():
            return True
        if exe.exists():
            log.warning(
                "Piper binary found but voice assets missing for '%s'", voice_name
            )
        return False

    async def start(self):
        TTS_OUT_WAV.parent.mkdir(parents=True, exist_ok=True)
        self._worker_task = asyncio.create_task(self._worker())
        log.info(f"TTS service started (backend: {self._backend})")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()

    # ── Public API ────────────────────────────────────────────────
    async def speak(self, text: str, priority: bool = False):
        if not text.strip():
            return
        if priority:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        await self._queue.put(text)
        log.info(f"TTS queued: {text[:60]!r}")

    async def synthesize(self, text: str, voice: str | None = None) -> Path:
        if not text.strip():
            raise ValueError("No text provided for synthesis")
        TTS_OUT_WAV.parent.mkdir(parents=True, exist_ok=True)

        if self._backend == "piper":
            path = await asyncio.get_event_loop().run_in_executor(
                None,
                self._speak_piper,
                text,
                TTS_OUT_WAV,
                False,
                voice or settings.voice.piper_voice,
            )
            return path

        if self._backend == "edge_tts":
            return await self._speak_edge(text, output_path=TTS_OUT_MP3, play=False)

        if self._backend == "pyttsx3":
            path = await asyncio.get_event_loop().run_in_executor(
                None,
                self._synthesize_pyttsx3_file,
                text,
                TTS_OUT_WAV,
            )
            return path

        raise RuntimeError("No TTS backend available")

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    async def wait_until_done(self, timeout: float = 60.0):
        """Block until the TTS queue is empty and playback has finished."""
        await asyncio.sleep(0.25)   # let the worker pick up the item
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if not self._speaking and self._queue.empty():
                return
            await asyncio.sleep(0.1)

    # ── Queue worker ──────────────────────────────────────────────
    async def _worker(self):
        while True:
            try:
                text = await self._queue.get()
                self._speaking = True
                if self._backend == "piper":
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._speak_piper, text)
                elif self._backend == "edge_tts":
                    await self._speak_edge(text)
                elif self._backend == "pyttsx3":
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._speak_pyttsx3, text)
                else:
                    log.warning(f"No TTS — skipping: {text[:40]}")
                self._speaking = False
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"TTS worker error: {e}")
                self._speaking = False

    # ── Edge TTS (async, high quality) ───────────────────────────
    async def _speak_edge(self, text: str, output_path: Path | None = None, play: bool = True) -> Path:
        try:
            import edge_tts

            out_path = output_path or TTS_OUT_MP3
            communicate = edge_tts.Communicate(text, EDGE_VOICE)
            await communicate.save(str(out_path))

            if play:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._play_audio, out_path)

            return out_path

        except Exception as e:
            log.error(f"edge-tts error: {e} — falling back to pyttsx3")
            if play:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._speak_pyttsx3, text)
                return TTS_OUT_WAV
            raise

    # ── Piper TTS (local binary) ──────────────────────────────────
    def _speak_piper(
        self,
        text: str,
        output_path: Path | None = None,
        play: bool = True,
        voice_name: str | None = None,
    ) -> Path:
        try:
            exe = PIPER_DIR / "piper.exe"
            voice_name = voice_name or settings.voice.piper_voice or "en_US-lessac-medium"
            model_file = PIPER_DIR / f"{voice_name}.onnx"
            config_file = PIPER_DIR / f"{voice_name}.onnx.json"
            out_path = output_path or TTS_OUT_WAV
            if not exe.exists() or not model_file.exists() or not config_file.exists():
                raise FileNotFoundError(
                    f"Piper assets missing for {voice_name}: {exe}, {model_file}, {config_file}"
                )
            args = [
                str(exe),
                "-m", str(model_file),
                "-c", str(config_file),
                "-f", str(out_path),
                "--quiet",
            ]
            proc = subprocess.run(
                args,
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
            if play:
                self._play_audio(out_path)
            return out_path
        except Exception as e:
            log.error(f"Piper TTS error: {e} — falling back to pyttsx3")
            if play:
                self._speak_pyttsx3(text)
                return TTS_OUT_WAV
            raise

    # ── pyttsx3 fallback ──────────────────────────────────────────
    def _speak_pyttsx3(self, text: str):
        try:
            import pyttsx3
            if self._engine is None:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", 165)
                self._engine.setProperty("volume", 1.0)
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as e:
            log.error(f"pyttsx3 error: {e}")
            self._engine = None

    def _synthesize_pyttsx3_file(self, text: str, output_path: Path) -> Path:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 165)
            engine.setProperty("volume", 1.0)
            engine.save_to_file(text, str(output_path))
            engine.runAndWait()
            return output_path
        except Exception as e:
            log.error(f"pyttsx3 synthesis error: {e}")
            raise

    # ── Audio playback ────────────────────────────────────────────
    def _play_audio(self, path: Path):
        if not path.exists() or path.stat().st_size == 0:
            log.warning(f"Audio file empty or missing: {path}")
            return
        try:
            # Try pygame first (best compatibility)
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                import time
                time.sleep(0.1)
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            return
        except ImportError:
            pass
        try:
            # playsound fallback
            from playsound import playsound
            playsound(str(path))
            return
        except ImportError:
            pass
        try:
            # Windows built-in for wav files
            import winsound
            if str(path).endswith(".wav"):
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
                return
            # Convert mp3 to wav using soundfile if needed
            import soundfile as sf
            import sounddevice as sd
            data, sr = sf.read(str(path))
            sd.play(data, sr)
            sd.wait()
        except Exception as e:
            log.error(f"Audio playback failed: {e}")
            log.info("Install pygame for best audio: pip install pygame")


# Singleton
tts_service = TTSService()
