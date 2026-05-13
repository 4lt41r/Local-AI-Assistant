"""
backend/routers/tools.py — Tool registry inspection + manual execution endpoints
"""

import json
import logging
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from services.tools_service import tools_service, TOOL_SCHEMAS, TOOL_MAP, TOOL_LOG

log = logging.getLogger("jarvis.tools_router")
router = APIRouter()


class ToolCallRequest(BaseModel):
    name: str
    args: dict = {}


# ── List available tools ───────────────────────────────────────
@router.get("/tools")
async def list_tools():
    return {
        "count": len(TOOL_SCHEMAS),
        "tools": [
            {
                "name":        s["function"]["name"],
                "description": s["function"]["description"],
                "parameters":  list(s["function"]["parameters"]["properties"].keys()),
            }
            for s in TOOL_SCHEMAS
        ],
    }


# ── Execute a tool manually ────────────────────────────────────
@router.post("/tools/run")
async def run_tool(req: ToolCallRequest):
    if req.name not in TOOL_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {req.name}")
    result = await tools_service.execute(req.name, req.args)
    return {"tool": req.name, "result": result}


# ── Last N tool call audit log entries ────────────────────────
@router.get("/tools/log")
async def tool_log(limit: int = 50):
    if not TOOL_LOG.exists():
        return {"entries": []}
    lines = TOOL_LOG.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return {"entries": list(reversed(entries))}
