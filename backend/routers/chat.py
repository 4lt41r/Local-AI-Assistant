"""
backend/routers/chat.py — Chat endpoints with persistent memory + tool use
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.router_engine import router_engine, SYSTEM_PROMPTS
from services.memory_service import memory_service
from services.activity_log import log_event

log = logging.getLogger("jarvis.chat")
router = APIRouter()

SYSTEM_PROMPT = (
    "You are JARVIS, an advanced local AI assistant. "
    "Be concise and helpful. Remember the conversation context. "
    "Use tools whenever they would give a more accurate or useful answer."
)


class ChatRequest(BaseModel):
    message:    str
    model:      Optional[str] = None
    session_id: str = "default"
    use_tools:  bool = True     # set False to skip the ReAct loop


class ChatResponse(BaseModel):
    response:        str
    model:           str
    task_type:       str
    session_id:      str
    tool_iterations: int = 0


# ── REST endpoint ─────────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    history      = memory_service.get_history(req.session_id)
    user_context = memory_service.get_system_context()

    if req.use_tools:
        result = await router_engine.route_with_tools(
            req.message,
            model_override=req.model,
            history=history,
            user_context=user_context,
        )
    else:
        result = await router_engine.route(
            req.message,
            model_override=req.model,
            history=history,
            user_context=user_context,
        )

    memory_service.add_turn(req.session_id, "user",      req.message)
    memory_service.add_turn(req.session_id, "assistant", result["response"])

    return ChatResponse(
        response=result["response"],
        model=result["model"],
        task_type=result["task_type"],
        session_id=req.session_id,
        tool_iterations=result.get("tool_iterations", 0),
    )


# ── Streaming endpoint ────────────────────────────────────────
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    Streaming for non-tool requests (tool-use requires full round-trips).
    For tool-aware requests, buffers the full response then streams it token by token.
    """
    from services.ollama_manager import ollama_manager
    from services.task_classifier import task_classifier

    history      = memory_service.get_history(req.session_id)
    user_context = memory_service.get_system_context()

    if req.use_tools:
        # Tool loop runs first (not streamable), then we emit tokens from the result
        result = await router_engine.route_with_tools(
            req.message,
            model_override=req.model,
            history=history,
            user_context=user_context,
        )
        response_text = result["response"]
        model         = result["model"]
        task_type     = result["task_type"]
        tool_iters    = result.get("tool_iterations", 0)

        memory_service.add_turn(req.session_id, "user",      req.message)
        memory_service.add_turn(req.session_id, "assistant", response_text)

        async def emit_buffered():
            # Emit the pre-computed response word by word so the UI still animates
            words = response_text.split(" ")
            for i, w in enumerate(words):
                token = w + ("" if i == len(words) - 1 else " ")
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, 'model': model, 'task_type': task_type, 'tool_iterations': tool_iters})}\n\n"

        return StreamingResponse(emit_buffered(), media_type="text/event-stream")

    # No tools — true streaming via /api/generate
    result    = task_classifier.classify_full(req.message)
    task_type = result.task_type
    model     = req.model or router_engine._pick_model(task_type)
    system    = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPT)
    prompt    = memory_service.build_prompt(req.session_id, req.message, system)
    full      = []

    async def event_stream():
        async for chunk in ollama_manager.stream_generate(model=model, prompt=prompt):
            if chunk.get("done"):
                memory_service.add_turn(req.session_id, "user",      req.message)
                memory_service.add_turn(req.session_id, "assistant", "".join(full))
                yield f"data: {json.dumps({'done': True, 'model': model, 'task_type': task_type})}\n\n"
            else:
                tok = chunk.get("token", "")
                full.append(tok)
                yield f"data: {json.dumps({'token': tok})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Fetch history (used by UI on mount to restore messages) ───
@router.get("/chat/history")
async def get_history(session_id: str = "default", limit: int = 60):
    messages = memory_service.get_history(session_id, limit=limit)
    return {
        "session_id": session_id,
        "messages":   messages,
        "count":      len(messages),
    }


# ── Clear history ─────────────────────────────────────────────
@router.post("/chat/clear")
async def clear_memory(session_id: str = "default"):
    memory_service.clear_history(session_id)
    return {"status": "cleared", "session_id": session_id}


# ── Profile endpoints ─────────────────────────────────────────
@router.get("/chat/profile")
async def get_profile():
    return memory_service.get_profile()


@router.post("/chat/profile")
async def update_profile(data: dict):
    for key, value in data.items():
        if key in ("name", "location"):
            memory_service.update_profile(key, value)
        elif key == "preferences" and isinstance(value, dict):
            for pk, pv in value.items():
                memory_service.add_preference(pk, pv)
        elif key == "fact" and isinstance(value, str):
            memory_service.add_fact(value)
    return {"status": "updated", "profile": memory_service.get_profile()}


# ── WebSocket (streaming + tools) ────────────────────────────
@router.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    session_id = "ws_default"
    log.info("WebSocket client connected")

    try:
        while True:
            raw      = await ws.receive_text()
            data     = json.loads(raw)
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                message    = data.get("message", "")
                model_req  = data.get("model")
                session_id = data.get("session_id", session_id)
                use_tools  = data.get("use_tools", True)

                history      = memory_service.get_history(session_id)
                user_context = memory_service.get_system_context()

                await ws.send_json({"type": "thinking"})

                if use_tools:
                    async def _status_cb(phase: str, detail=None):
                        msg = {"type": "status", "phase": phase}
                        if detail:
                            msg["detail"] = detail
                        try:
                            await ws.send_json(msg)
                        except Exception:
                            pass

                    result = await router_engine.route_with_tools(
                        message,
                        model_override=model_req,
                        history=history,
                        user_context=user_context,
                        status_cb=_status_cb,
                    )
                    response_text = result["response"]
                    memory_service.add_turn(session_id, "user",      message)
                    memory_service.add_turn(session_id, "assistant", response_text)
                    log_event("chat", f"Q: {message[:60]}", f"A: {response_text[:60]}")
                    await ws.send_json({
                        "type":            "done",
                        "response":        response_text,
                        "model":           result["model"],
                        "task_type":       result["task_type"],
                        "tool_iterations": result.get("tool_iterations", 0),
                    })
                else:
                    from services.ollama_manager import ollama_manager
                    from services.task_classifier import task_classifier
                    cls       = task_classifier.classify_full(message)
                    task_type = cls.task_type
                    model     = model_req or router_engine._pick_model(task_type)
                    system    = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPT)
                    prompt    = memory_service.build_prompt(session_id, message, system)
                    full      = []
                    async for chunk in ollama_manager.stream_generate(model=model, prompt=prompt):
                        if chunk.get("done"):
                            memory_service.add_turn(session_id, "user",      message)
                            memory_service.add_turn(session_id, "assistant", "".join(full))
                            await ws.send_json({"type": "done", "model": model, "task_type": task_type})
                        else:
                            tok = chunk.get("token", "")
                            full.append(tok)
                            await ws.send_json({"type": "token", "token": tok})

            elif msg_type == "clear":
                memory_service.clear_history(data.get("session_id", session_id))
                await ws.send_json({"type": "cleared"})

            elif msg_type == "profile":
                await ws.send_json({"type": "profile", "data": memory_service.get_profile()})

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        log.info("WebSocket disconnected")
    except Exception as e:
        log.error(f"WebSocket error: {e}")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
