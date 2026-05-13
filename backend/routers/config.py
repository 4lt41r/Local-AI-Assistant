"""
backend/routers/config.py — Config read/write endpoints
"""

import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from config import settings

log = logging.getLogger("jarvis.config")
router = APIRouter()


@router.get("/config")
async def get_config():
    return settings.model_dump()


@router.post("/config")
async def save_config(payload: dict):
    """Merge and persist config changes."""
    try:
        current = settings.model_dump()
        _deep_merge(current, payload)
        # Re-validate via Settings model
        from config import Settings
        updated = Settings(**current)
        updated.save()
        # Update in-memory singleton fields
        for k, v in updated.model_dump().items():
            if hasattr(settings, k):
                try:
                    object.__setattr__(settings, k, v)
                except Exception:
                    pass
        return {"status": "saved"}
    except Exception as e:
        log.error(f"Config save error: {e}")
        return {"status": "error", "detail": str(e)}


def _deep_merge(base: dict, override: dict):
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
