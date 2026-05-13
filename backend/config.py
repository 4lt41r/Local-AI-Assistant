"""
backend/config.py — Central configuration
Loads from config/jarvis.json relative to JARVIS install root
"""

import json
import os
from pathlib import Path
from pydantic import BaseModel
from typing import Optional


def _find_install_root() -> Path:
    """Walk up from backend/ to find jarvis.json"""
    here = Path(__file__).resolve().parent  # backend/
    for candidate in [here.parent, here]:
        if (candidate / "config" / "jarvis.json").exists():
            return candidate
    # Fallback: env var
    env = os.environ.get("JARVIS_ROOT")
    if env:
        return Path(env)
    return here.parent


INSTALL_ROOT = _find_install_root()
CONFIG_PATH  = INSTALL_ROOT / "config" / "jarvis.json"


class VoiceConfig(BaseModel):
    wake_word:    str = "hey jarvis"
    whisper_model: str = "base.en"
    piper_voice:  str = "en_US-lessac-medium"
    enabled:      bool = True


class GpuConfig(BaseModel):
    num_gpu:      int   = 1
    vram_limit_gb: float = 4.0


class ModelsConfig(BaseModel):
    code:      str = "qwen2.5-coder:7b"
    reasoning: str = "deepseek-r1:7b"
    general:   str = "llama3.1:8b"
    vision:    str = "llava:7b"


class Settings(BaseModel):
    version:          str = "1.0.0"
    install_root:     str = str(INSTALL_ROOT)
    backend_port:     int = 8000
    electron_port:    int = 3000
    ollama_host:      str = "http://localhost:11434"
    ollama_keep_alive: str = "5m"
    default_model:    str = "llama3.1:8b"
    models:           ModelsConfig = ModelsConfig()
    voice:            VoiceConfig  = VoiceConfig()
    gpu:              GpuConfig    = GpuConfig()

    @classmethod
    def load(cls) -> "Settings":
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return cls(**raw)
            except Exception as e:
                print(f"[config] Warning: could not parse jarvis.json: {e}")
        return cls()

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(self.model_dump_json(indent=2), encoding="utf-8")


# Singleton — import this everywhere
settings = Settings.load()
