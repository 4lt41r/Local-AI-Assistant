"""
backend/services/router_engine.py — AI task routing orchestrator
Classifies prompt → selects model → dispatches to Ollama
"""

import logging
from typing import Optional, AsyncGenerator

from config import settings
from services.task_classifier import task_classifier, ClassificationResult
from services.ollama_manager import ollama_manager
from services.tools_service import tools_service, TOOL_SCHEMAS

log = logging.getLogger("jarvis.router")

SYSTEM_PROMPTS = {
    "general": (
        "You are JARVIS, an advanced local AI assistant. "
        "Be concise, clear, and helpful. "
        "Remember what the user has told you earlier in this conversation."
    ),
    "code": (
        "You are JARVIS, an expert software engineer. "
        "Provide working, production-quality code. "
        "Include brief inline comments for non-obvious logic. "
        "Use markdown code blocks with language tags."
    ),
    "reasoning": (
        "You are JARVIS, an analytical AI. "
        "Think step-by-step. Show your reasoning clearly. "
        "Weigh trade-offs and give structured conclusions."
    ),
    "vision": (
        "You are JARVIS, a vision-capable AI assistant. "
        "Describe images accurately and in detail."
    ),
}


def _build_prompt(
    message: str,
    system: str,
    history: Optional[list] = None,
    user_context: str = "",
) -> str:
    """Format conversation history + user profile + message for Ollama."""
    if user_context:
        system = f"{system}\n\n{user_context}"
    if not history:
        return message
    parts = [f"System: {system}\n"]
    for msg in history:
        prefix = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"{prefix}: {msg['content']}")
    parts.append(f"User: {message}")
    parts.append("Assistant:")
    return "\n".join(parts)


class RouterEngine:

    async def route(
        self,
        message: str,
        model_override: Optional[str] = None,
        history: Optional[list] = None,
        user_context: str = "",
    ) -> dict:
        """Classify → select model → generate (non-streaming)."""

        if model_override:
            model      = model_override
            task_type  = "general"
            confidence = 1.0
        else:
            result     = task_classifier.classify_full(message)
            task_type  = result.task_type
            confidence = result.confidence
            model      = self._pick_model(task_type)

        log.info(f"[route] task={task_type} conf={confidence:.2f} model={model}")

        system = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPTS["general"])
        prompt = _build_prompt(message, system, history, user_context)

        gen = await ollama_manager.generate(model=model, prompt=prompt, system=system)

        return {
            "response":    gen["response"],
            "model":       model,
            "task_type":   task_type,
            "confidence":  confidence,
        }

    async def stream(
        self,
        message: str,
        model_override: Optional[str] = None,
        history: Optional[list] = None,
        user_context: str = "",
    ) -> AsyncGenerator[dict, None]:
        """Classify → select model → stream tokens."""

        if model_override:
            model      = model_override
            task_type  = "general"
            confidence = 1.0
        else:
            result     = task_classifier.classify_full(message)
            task_type  = result.task_type
            confidence = result.confidence
            model      = self._pick_model(task_type)

        log.info(f"[stream] task={task_type} conf={confidence:.2f} model={model}")

        system = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPTS["general"])
        prompt = _build_prompt(message, system, history, user_context)

        async for chunk in ollama_manager.stream_generate(
            model=model, prompt=prompt, system=system
        ):
            if chunk.get("done"):
                yield {
                    "done":       True,
                    "model":      model,
                    "task_type":  task_type,
                    "confidence": confidence,
                }
            else:
                yield {"token": chunk.get("token", ""), "done": False}

    async def route_with_tools(
        self,
        message: str,
        model_override: Optional[str] = None,
        history: Optional[list] = None,
        user_context: str = "",
        status_cb=None,
    ) -> dict:
        """
        Agentic route: classify → pick tool-capable model → ReAct loop.
        deepseek-r1 (reasoning) and llava (vision) don't support tool-calling,
        so those task types fall through to the regular generate() path.

        status_cb: optional async callable(phase: str, detail: str | None)
          emits "ROUTING", "THINKING", "TOOL" phases to the caller.
        """
        if status_cb:
            try:
                await status_cb("ROUTING", None)
            except Exception:
                pass

        result     = task_classifier.classify_full(message)
        task_type  = result.task_type
        confidence = result.confidence

        # Models that don't support tool-calling fall back to plain generate
        if task_type in ("reasoning", "vision") and not model_override:
            log.info(f"[route_with_tools] task={task_type} — tool calling unsupported, falling back")
            return await self.route(message, history=history, user_context=user_context)

        model  = model_override or self._pick_tool_model(task_type)
        system = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPTS["general"])
        if user_context:
            system = f"{system}\n\n{user_context}"

        # Convert history to /api/chat message format
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in (history or [])
        ]
        messages.append({"role": "user", "content": message})

        log.info(f"[route_with_tools] task={task_type} conf={confidence:.2f} model={model}")

        gen = await ollama_manager.chat_with_tools(
            model=model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            system=system,
            tool_executor=tools_service.execute,
            status_cb=status_cb,
        )

        return {
            "response":        gen["response"],
            "model":           model,
            "task_type":       task_type,
            "confidence":      confidence,
            "tool_iterations": gen.get("iterations", 1),
        }

    def _pick_tool_model(self, task_type: str) -> str:
        """Pick a model that supports tool/function calling."""
        m = settings.models
        # llava doesn't support tools; code and general do
        return m.code if task_type == "code" else m.general

    def _pick_model(self, task_type: str) -> str:
        m = settings.models
        return {
            "code":      m.code,
            "reasoning": m.reasoning,
            "vision":    m.vision,
            "general":   m.general,
        }.get(task_type, m.general)

    def debug_classify(self, prompt: str) -> dict:
        """Return full classification debug info."""
        result = task_classifier.classify_full(prompt)
        return {
            "task_type":  result.task_type,
            "confidence": result.confidence,
            "scores":     result.scores,
            "signals":    result.signals[:20],
            "model":      self._pick_model(result.task_type),
        }


# Singleton
router_engine = RouterEngine()
