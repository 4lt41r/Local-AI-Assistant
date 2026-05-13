"""
backend/services/voice_stt.py — STT service
Uses faster-whisper (Python package) instead of whisper.cpp binary.
No external exe needed — works on any Windows x64 with Python 3.11.

Install: pip install faster-whisper sounddevice soundfile numpy
"""

import asyncio
import logging
import subprocess
import time
import wave
from pathlib import Path
from typing import Optional, Callable

from config import INSTALL_ROOT, settings

log = logging.getLogger("jarvis.stt")

TEMP_WAV    = INSTALL_ROOT / "logs" / "stt_input.wav"
TRANSCRIPT_TXT = INSTALL_ROOT / "logs" / "stt_transcript.txt"
SAMPLE_RATE = 16000
CHANNELS    = 1
WHISPER_DOWNLOAD_ROOT = INSTALL_ROOT / "models" / "whisper"
WHISPER_MODEL_NAME = settings.voice.whisper_model or "small"
WHISPER_CPP_ROOT = INSTALL_ROOT / "voice" / "whisper"
WHISPER_CPP_EXE = WHISPER_CPP_ROOT / "stream.exe"


def _whisper_cpp_model_path(model_name: str) -> Path:
    if model_name.endswith(".bin"):
        return WHISPER_CPP_ROOT / model_name
    return WHISPER_CPP_ROOT / f"ggml-{model_name}.bin"


class STTService:

    def __init__(self):
        self._listening  = False
        self._frames     = []
        self._task: Optional[asyncio.Task] = None
        self._model      = None          # lazy-loaded on first use
        self._audio_backend = self._detect_audio()

    def _detect_audio(self) -> str:
        try:
            import sounddevice
            return "sounddevice"
        except ImportError:
            pass
        try:
            import pyaudio
            return "pyaudio"
        except ImportError:
            pass
        if WHISPER_CPP_EXE.exists():
            log.info("No Python audio backend available; falling back to whisper.cpp capture")
            return "whisper_cpp"
        log.warning("No audio backend. Run: pip install sounddevice or pyaudio")
        return "none"

    def _load_model(self):
        """Lazy-load faster-whisper model on first transcription."""
        if self._model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            model_name = settings.voice.whisper_model or WHISPER_MODEL_NAME
            log.info(f"Loading faster-whisper model: {model_name}")
            # device="cpu" works on all machines
            # compute_type="int8" is fastest on CPU
            self._model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(WHISPER_DOWNLOAD_ROOT),
            )
            log.info("faster-whisper model ready")
            return True
        except ImportError:
            log.error("faster-whisper not installed. Run: pip install faster-whisper")
            return False
        except Exception as e:
            log.error(f"faster-whisper load error: {e}")
            return False

    # ── Public API ────────────────────────────────────────────────
    async def start(self, on_wake: Optional[Callable] = None):
        if self._listening:
            return
        if self._audio_backend == "none":
            log.error("No audio backend. Run: pip install sounddevice")
            return
        self._frames    = []
        self._listening = True
        self._task      = asyncio.create_task(self._capture_loop())
        log.info(f"STT: started ({self._audio_backend})")

    async def stop(self) -> dict:
        if not self._listening:
            return {"transcript": ""}
        self._listening = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._audio_backend == "whisper_cpp":
            transcript = await self._transcribe_whisper_cpp()
            log.info(f"STT transcript: {transcript!r}")
            return {"transcript": transcript}

        if not self._frames:
            return {"transcript": ""}

        await self._save_wav()
        transcript = await self._transcribe(TEMP_WAV)
        log.info(f"STT transcript: {transcript!r}")
        return {"transcript": transcript}

    @property
    def is_listening(self) -> bool:
        return self._listening

    # ── Audio capture ─────────────────────────────────────────────
    async def _capture_loop(self):
        loop = asyncio.get_event_loop()
        if self._audio_backend == "sounddevice":
            await loop.run_in_executor(None, self._capture_sounddevice)
        elif self._audio_backend == "pyaudio":
            await loop.run_in_executor(None, self._capture_pyaudio)
        elif self._audio_backend == "whisper_cpp":
            await loop.run_in_executor(None, self._capture_whisper_cpp)

    def _capture_sounddevice(self):
        import sounddevice as sd
        log.info("STT: sounddevice capture started")
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype="int16", blocksize=1024
        ) as stream:
            while self._listening:
                data, _ = stream.read(1024)
                self._frames.append(data.tobytes())

    def _capture_pyaudio(self):
        import pyaudio
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16, channels=CHANNELS,
            rate=SAMPLE_RATE, input=True, frames_per_buffer=1024
        )
        while self._listening:
            try:
                self._frames.append(stream.read(1024, exception_on_overflow=False))
            except Exception:
                break
        stream.stop_stream()
        stream.close()
        pa.terminate()

    def _capture_whisper_cpp(self):
        model = settings.voice.whisper_model or WHISPER_MODEL_NAME
        model_path = _whisper_cpp_model_path(model)
        if not model_path.exists():
            log.error(f"whisper.cpp model not found: {model_path}")
            return

        TRANSCRIPT_TXT.parent.mkdir(parents=True, exist_ok=True)
        if TRANSCRIPT_TXT.exists():
            TRANSCRIPT_TXT.unlink()

        args = [
            str(WHISPER_CPP_EXE),
            "--model", str(model_path),
            "--language", "en",
            "--file", str(TRANSCRIPT_TXT),
            "--save-audio",
            "--step", "3000",
            "--length", "6000",
            "--keep", "200",
        ]

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            while self._listening and proc.poll() is None:
                time.sleep(0.1)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception as e:
            log.error(f"whisper.cpp capture failed: {e}")

    async def _transcribe_whisper_cpp(self) -> str:
        if not TRANSCRIPT_TXT.exists():
            return ""
        try:
            return TRANSCRIPT_TXT.read_text(encoding="utf-8").strip()
        except Exception as e:
            log.error(f"Failed to read whisper.cpp transcript: {e}")
            return ""

    # ── WAV save ──────────────────────────────────────────────────
    async def _save_wav(self):
        TEMP_WAV.parent.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._write_wav)

    def _write_wav(self):
        with wave.open(str(TEMP_WAV), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            data = b"".join(self._frames)
            wf.writeframes(data)
        duration = len(self._frames) * 1024 / SAMPLE_RATE
        log.info(f"STT: recorded {duration:.1f}s of audio ({len(data)} bytes)")

    # ── Transcription via faster-whisper ──────────────────────────
    async def _transcribe(self, wav_path: Path) -> str:
        if not wav_path.exists():
            return ""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run_faster_whisper, wav_path)

    def _run_faster_whisper(self, wav_path: Path) -> str:
        if not self._load_model():
            return ""
        try:
            segments, info = self._model.transcribe(
                str(wav_path),
                language="en",
                beam_size=5,
                best_of=5,
                # temperature fallback: tries 0.0 first (deterministic), then 0.2 if
                # quality is low — handles Indian retroflex consonants and vowel shifts
                temperature=[0.0, 0.2],
                # biases Whisper toward expected phrases — significantly helps with accents
                initial_prompt="Jarvis. Hey Jarvis. Yes? What can I do for you?",
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.15,               # very sensitive — catches quiet/accented speech
                    min_speech_duration_ms=100,
                    min_silence_duration_ms=400,
                    speech_pad_ms=800,            # wider padding so clipped syllables are kept
                ),
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text
        except Exception as e:
            log.error(f"Transcription error: {e}")
            return ""

    # ── Wake word ─────────────────────────────────────────────────
    def check_wake_word(self, transcript: str) -> bool:
        text = transcript.lower().strip()
        if not text:
            return False
        wake = settings.voice.wake_word.lower().strip()
        if wake in text:
            return True
        # Fallback variants: common Whisper transcription errors for "Jarvis"
        # with Indian English phonology (dropped R, vowel shift, syllable stress)
        return any(v in text for v in ["jarvis", "jarv", "jaavis", "jervis", "jarv is"])


# Singleton
stt_service = STTService()
