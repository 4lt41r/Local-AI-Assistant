"""
backend/routers/models.py — Model management endpoints (Phase 5 enhanced)
"""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.ollama_manager import ollama_manager
from services.model_manager import model_manager, ALL_MODELS

log = logging.getLogger("jarvis.models")
router = APIRouter()


class LoadRequest(BaseModel):
    name: str

class SwitchRequest(BaseModel):
    model: str

class RoutingUpdate(BaseModel):
    role:  str
    model: str

class PullRequest(BaseModel):
    name: str


@router.get("")
async def list_models():
    return await model_manager.get_status()

@router.get("/active")
async def active_model():
    return {"active_model": ollama_manager.active_model}

@router.get("/supported")
async def supported_models():
    return {"models": ALL_MODELS}

@router.post("/load")
async def load_model(req: LoadRequest):
    ok = await ollama_manager.ensure_loaded(req.name)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to load {req.name}")
    return {"status": "loaded", "model": req.name}

@router.post("/switch")
async def switch_model(req: SwitchRequest):
    return await model_manager.switch_to(req.model)

@router.post("/unload")
async def unload_model(req: LoadRequest):
    return await ollama_manager.unload_model(req.name)

@router.post("/unload/current")
async def unload_current():
    return await model_manager.unload_current()

@router.post("/pull")
async def pull_model(req: PullRequest):
    return await model_manager.queue_pull(req.name)

@router.post("/pull/all")
async def pull_all():
    queued = await model_manager.pull_all_missing()
    return {"status": "queued", "models": queued}

@router.get("/pull/stream/{name}")
async def pull_stream(name: str):
    async def event_stream():
        import json, httpx
        from config import settings
        async with httpx.AsyncClient(base_url=settings.ollama_host, timeout=600.0) as client:
            async with client.stream("POST", "/api/pull", json={"name": name}) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        yield f"data: {line}\n\n"
        yield 'data: {"done": true}\n\n'
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/routing")
async def get_routing():
    return model_manager.get_routing()

@router.post("/routing")
async def update_routing(req: RoutingUpdate):
    return model_manager.update_routing(req.role, req.model)
