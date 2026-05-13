"""
backend/services/model_manager.py — High-level model orchestration
Handles:
- VRAM budget enforcement (one model at a time)
- Model status tracking
- Pull queue (sequential to avoid OOM)
- Routing config hot-reload
"""

import asyncio
import logging
from typing import Optional

from config import settings
from services.ollama_manager import ollama_manager

log = logging.getLogger("jarvis.modelmanager")

# All models JARVIS supports
ALL_MODELS = [
    "llama3.1:8b",
    "qwen2.5-coder:7b",
    "deepseek-r1:7b",
    "llava:7b",
]


class ModelManager:

    def __init__(self):
        self._pull_queue: asyncio.Queue = asyncio.Queue()
        self._pull_task:  Optional[asyncio.Task] = None

    async def start(self):
        """Start background pull worker."""
        self._pull_task = asyncio.create_task(self._pull_worker())

    async def stop(self):
        if self._pull_task:
            self._pull_task.cancel()

    # ── Status ────────────────────────────────────────────────────
    async def get_status(self) -> dict:
        """Full model status: installed, active, routing."""
        installed_data = await ollama_manager.list_models()
        installed_names = {m["name"] for m in installed_data.get("models", [])}

        models_status = []
        for name in ALL_MODELS:
            short = name.split(":")[0]
            is_installed = name in installed_names or any(
                short in n for n in installed_names
            )
            models_status.append({
                "name":       name,
                "installed":  is_installed,
                "active":     ollama_manager.active_model == name,
                "role":       ollama_manager._model_role(name),
                "vram_est":   self._vram_estimate(name),
            })

        return {
            "models":       models_status,
            "active_model": ollama_manager.active_model,
            "routing": {
                "general":   settings.models.general,
                "code":      settings.models.code,
                "reasoning": settings.models.reasoning,
                "vision":    settings.models.vision,
            },
        }

    # ── VRAM estimates (Q4 quantized 7-8B) ───────────────────────
    def _vram_estimate(self, name: str) -> str:
        estimates = {
            "llama3.1:8b":        "~4.0 GB",
            "qwen2.5-coder:7b":   "~3.8 GB",
            "deepseek-r1:7b":     "~3.8 GB",
            "llava:7b":           "~4.0 GB",
        }
        return estimates.get(name, "~4 GB")

    # ── Model switching ───────────────────────────────────────────
    async def switch_to(self, model: str) -> dict:
        """
        Explicitly switch active model.
        Unloads current → loads new.
        """
        if model not in ALL_MODELS:
            return {"error": f"Unknown model: {model}"}

        current = ollama_manager.active_model
        if current == model:
            return {"status": "already_active", "model": model}

        log.info(f"Switching model: {current} → {model}")
        ok = await ollama_manager.ensure_loaded(model)
        return {
            "status":  "switched" if ok else "failed",
            "model":   model,
            "previous": current,
        }

    async def unload_current(self) -> dict:
        """Unload active model — frees VRAM."""
        model = ollama_manager.active_model
        if not model:
            return {"status": "no_model_loaded"}
        await ollama_manager.unload_model(model)
        return {"status": "unloaded", "model": model}

    # ── Pull queue (sequential — prevents OOM during concurrent pulls) ─
    async def queue_pull(self, model: str) -> dict:
        """Add model to pull queue. Returns immediately."""
        await self._pull_queue.put(model)
        log.info(f"Queued pull: {model}")
        return {"status": "queued", "model": model}

    async def pull_all_missing(self) -> list:
        """Queue all missing models for pull."""
        installed_data = await ollama_manager.list_models()
        installed_names = {m["name"] for m in installed_data.get("models", [])}
        queued = []
        for name in ALL_MODELS:
            short = name.split(":")[0]
            if name not in installed_names and not any(short in n for n in installed_names):
                await self.queue_pull(name)
                queued.append(name)
        return queued

    async def _pull_worker(self):
        """Sequential pull worker — processes queue one at a time."""
        while True:
            try:
                model = await self._pull_queue.get()
                log.info(f"[pull worker] Pulling: {model}")
                result = await ollama_manager.ensure_model(model)
                log.info(f"[pull worker] Done: {model} — {result}")
                self._pull_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[pull worker] Error: {e}")

    # ── Routing config ────────────────────────────────────────────
    def get_routing(self) -> dict:
        return {
            "general":   settings.models.general,
            "code":      settings.models.code,
            "reasoning": settings.models.reasoning,
            "vision":    settings.models.vision,
        }

    def update_routing(self, role: str, model: str) -> dict:
        """Hot-update routing without restart."""
        valid_roles = {"general", "code", "reasoning", "vision"}
        if role not in valid_roles:
            return {"error": f"Invalid role: {role}"}
        if model not in ALL_MODELS:
            return {"error": f"Unknown model: {model}"}

        setattr(settings.models, role, model)
        settings.save()
        log.info(f"Routing updated: {role} → {model}")
        return {"status": "updated", "role": role, "model": model}


# Singleton
model_manager = ModelManager()
