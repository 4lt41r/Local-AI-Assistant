"""
backend/services/ollama_manager.py — Ollama lifecycle management
- Auto-start Ollama process
- Lazy model loading (load on first request)
- Auto-unload after idle timeout
- One model at a time (VRAM budget: RTX 3050 4GB)
- Model pull with progress streaming
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx
from config import settings, INSTALL_ROOT

log = logging.getLogger("jarvis.ollama")

OLLAMA_EXE = INSTALL_ROOT / "ollama" / "ollama.exe"
OLLAMA_SYS = shutil.which("ollama")
MODELS_DIR = INSTALL_ROOT / "models" / "ollama"


class OllamaManager:

    def __init__(self):
        self.base_url      = settings.ollama_host
        self.active_model: Optional[str] = None
        self._client:      Optional[httpx.AsyncClient] = None
        self._process:     Optional[subprocess.Popen] = None
        self._last_used:   float = 0.0
        self._lock         = asyncio.Lock()
        self._unload_task: Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────
    async def start(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(120.0, connect=5.0),
        )
        if await self.ping():
            log.info("Ollama already running")
            return

        exe = str(OLLAMA_EXE) if OLLAMA_EXE.exists() else OLLAMA_SYS
        if not exe:
            log.warning("Ollama binary not found — assuming external")
            return

        env = {
            **os.environ,
            "OLLAMA_MODELS":     str(MODELS_DIR),
            "OLLAMA_NUM_GPU":    str(settings.gpu.num_gpu),
            "OLLAMA_KEEP_ALIVE": settings.ollama_keep_alive,
        }
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [exe, "serve"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        log.info(f"Ollama process started from {exe}")
        for _ in range(24):
            await asyncio.sleep(0.5)
            if await self.ping():
                log.info("Ollama ready")
                return
        log.warning("Ollama did not respond within 12s")

    async def stop(self):
        if self._unload_task:
            self._unload_task.cancel()
        if self._client:
            await self._client.aclose()
        if self._process:
            self._process.terminate()

    # ── Health ────────────────────────────────────────────────────
    async def ping(self) -> bool:
        try:
            r = await self._client.get("/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    # ── Model discovery ───────────────────────────────────────────
    async def list_models(self) -> dict:
        try:
            r = await self._client.get("/api/tags")
            data = r.json()
            for m in data.get("models", []):
                m["routed_as"] = self._model_role(m["name"])
            return data
        except Exception as e:
            return {"models": [], "error": str(e)}

    def _model_role(self, name: str) -> str:
        m = settings.models
        roles = {
            m.code:      "code",
            m.reasoning: "reasoning",
            m.vision:    "vision",
            m.general:   "general",
        }
        for pattern, role in roles.items():
            if pattern.split(":")[0] in name:
                return role
        return "general"

    def _installed_names(self, data: dict) -> set:
        return {m["name"] for m in data.get("models", [])}

    # ── Lazy load / switch ────────────────────────────────────────
    async def ensure_loaded(self, model: str) -> bool:
        """Load model lazily; evict previous model first."""
        if self.active_model == model:
            self._touch()
            return True

        async with self._lock:
            if self.active_model and self.active_model != model:
                await self._force_unload(self.active_model)

            log.info(f"Loading model: {model}")
            try:
                r = await self._client.post("/api/generate", json={
                    "model": model, "prompt": "",
                    "keep_alive": settings.ollama_keep_alive,
                }, timeout=60.0)
                if r.status_code == 200:
                    self.active_model = model
                    self._touch()
                    self._schedule_idle_check()
                    log.info(f"Model loaded: {model}")
                    return True
            except Exception as e:
                log.error(f"Load error {model}: {e}")
        return False

    async def _force_unload(self, model: str):
        try:
            await self._client.post("/api/generate", json={
                "model": model, "prompt": "", "keep_alive": 0
            }, timeout=10.0)
            log.info(f"Unloaded: {model}")
        except Exception as e:
            log.warning(f"Unload error {model}: {e}")
        finally:
            if self.active_model == model:
                self.active_model = None

    async def unload_model(self, model: str) -> dict:
        await self._force_unload(model)
        return {"unloaded": True, "model": model}

    async def ensure_model(self, name: str) -> dict:
        """Pull model if not installed. Streams pull progress to log."""
        data = await self.list_models()
        if name in self._installed_names(data):
            return {"already_present": True, "model": name}

        log.info(f"Pulling: {name}")
        async with self._client.stream(
            "POST", "/api/pull", json={"name": name},
            timeout=httpx.Timeout(600.0)
        ) as resp:
            last = ""
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    s = chunk.get("status", "")
                    if s != last:
                        log.info(f"Pull [{name}]: {s}")
                        last = s
                    if s == "success":
                        return {"pulled": True, "model": name}
                except Exception:
                    continue
        return {"pulled": True, "model": name}

    # ── Idle auto-unload ──────────────────────────────────────────
    def _touch(self):
        self._last_used = time.monotonic()

    def _schedule_idle_check(self):
        if self._unload_task and not self._unload_task.done():
            return
        self._unload_task = asyncio.create_task(self._idle_watcher())

    async def _idle_watcher(self):
        ka = self._parse_keep_alive(settings.ollama_keep_alive)
        if ka <= 0:
            return
        while True:
            await asyncio.sleep(30)
            if not self.active_model:
                return
            if time.monotonic() - self._last_used >= ka:
                log.info(f"Idle timeout: unloading {self.active_model}")
                await self._force_unload(self.active_model)
                return

    @staticmethod
    def _parse_keep_alive(s: str) -> int:
        try:
            if s.endswith("m"):  return int(s[:-1]) * 60
            if s.endswith("h"):  return int(s[:-1]) * 3600
            if s.endswith("s"):  return int(s[:-1])
            return int(s)
        except Exception:
            return 300

    # ── /api/chat with tool-calling support ──────────────────────
    async def chat(
        self,
        model: str,
        messages: list,
        tools: list = [],
        system: str = "",
    ) -> dict:
        """Single round-trip to /api/chat. Returns the raw message dict."""
        await self.ensure_loaded(model)
        self._touch()
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        payload = {
            "model":      model,
            "messages":   msgs,
            "stream":     False,
            "keep_alive": settings.ollama_keep_alive,
        }
        if tools:
            payload["tools"] = tools
        r = await self._client.post("/api/chat", json=payload, timeout=120.0)
        return r.json()

    async def chat_with_tools(
        self,
        model: str,
        messages: list,
        tools: list,
        system: str = "",
        tool_executor=None,
        max_iterations: int = 8,
        status_cb=None,
    ) -> dict:
        """
        ReAct loop: call /api/chat, execute any tool_calls, feed results back,
        repeat until the model stops calling tools or max_iterations is reached.

        tool_executor: async callable(tool_name: str, args: dict) -> str
        status_cb: optional async callable(phase: str, detail: str | None)
        """
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs

        for iteration in range(max_iterations):
            if status_cb:
                try:
                    await status_cb("THINKING", None)
                except Exception:
                    pass
            data    = await self.chat(model, msgs, tools)
            msg     = data.get("message", {})
            content = msg.get("content", "")
            calls   = msg.get("tool_calls") or []

            if not calls:
                # No tool calls — final text response
                return {"response": content, "model": model, "iterations": iteration + 1}

            # Append the assistant turn (with tool_calls)
            msgs.append(msg)

            # Execute each requested tool and append results
            for tc in calls:
                fn   = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                log.info(f"[tool-call] {name}({list(args.keys())})")
                if status_cb:
                    try:
                        await status_cb("TOOL", name)
                    except Exception:
                        pass
                if tool_executor:
                    try:
                        result = await tool_executor(name, args)
                    except Exception as e:
                        result = f"Tool error: {e}"
                else:
                    result = "No tool executor configured."
                msgs.append({"role": "tool", "content": str(result)})

        # Max iterations — return whatever the model last said
        last_content = next(
            (m.get("content", "") for m in reversed(msgs) if m.get("role") == "assistant"),
            "Reached maximum tool iterations.",
        )
        return {"response": last_content, "model": model, "iterations": max_iterations}

    # ── Generation ────────────────────────────────────────────────
    async def generate(self, model: str, prompt: str, system: str = "") -> dict:
        await self.ensure_loaded(model)
        self._touch()
        payload = {
            "model": model, "prompt": prompt,
            "stream": False, "keep_alive": settings.ollama_keep_alive,
        }
        if system:
            payload["system"] = system
        r = await self._client.post("/api/generate", json=payload, timeout=120.0)
        data = r.json()
        return {"response": data.get("response", ""), "model": model}

    async def stream_generate(
        self, model: str, prompt: str, system: str = ""
    ) -> AsyncGenerator[dict, None]:
        await self.ensure_loaded(model)
        self._touch()
        payload = {
            "model": model, "prompt": prompt,
            "stream": True, "keep_alive": settings.ollama_keep_alive,
        }
        if system:
            payload["system"] = system
        async with self._client.stream(
            "POST", "/api/generate", json=payload,
            timeout=httpx.Timeout(120.0)
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    self._touch()
                    if chunk.get("done"):
                        yield {"done": True, "model": model}
                    else:
                        yield {"token": chunk.get("response", ""), "done": False}
                except Exception:
                    continue


# Singleton
ollama_manager = OllamaManager()
