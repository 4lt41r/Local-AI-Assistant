"""
backend/routers/system.py — System stats endpoint
"""

import logging
from fastapi import APIRouter
from services.system_monitor import system_monitor
from services.ollama_manager import ollama_manager

log = logging.getLogger("jarvis.system")
router = APIRouter()


@router.get("/stats")
async def get_stats():
    """RAM, CPU, VRAM, active model."""
    stats = system_monitor.get_stats()
    stats["active_model"] = ollama_manager.active_model or None
    return stats


@router.get("/health")
async def system_health():
    """Full health check: backend + ollama + models."""
    ollama_ok = await ollama_manager.ping()
    return {
        "backend": True,
        "ollama":  ollama_ok,
        "active_model": ollama_manager.active_model,
    }


@router.get("/activity")
async def get_activity(limit: int = 30):
    """Recent JARVIS activity: voice turns, chat turns, tool calls."""
    from services.activity_log import get_recent
    return {"events": get_recent(limit)}
