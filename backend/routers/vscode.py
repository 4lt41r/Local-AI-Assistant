"""
backend/routers/vscode.py — VS Code + coding workspace endpoints
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.workspace_manager import workspace_manager
from services.router_engine import router_engine

log = logging.getLogger("jarvis.vscode")
router = APIRouter()


class OpenRequest(BaseModel):
    path: str = ""

class OpenFileRequest(BaseModel):
    file_path: str
    line:      int = 1

class FileContextRequest(BaseModel):
    file_path:   str
    instruction: str

class CodeRequest(BaseModel):
    code:        str
    instruction: str
    language:    Optional[str] = None
    model:       Optional[str] = None

class TreeRequest(BaseModel):
    root:      str
    max_depth: int = 3


@router.post("/open")
async def open_vscode(req: OpenRequest = None):
    path   = req.path if req else ""
    result = workspace_manager.open_in_vscode(path)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.post("/open/file")
async def open_file(req: OpenFileRequest):
    result = workspace_manager.open_file_in_vscode(req.file_path, req.line)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@router.get("/status")
async def vscode_status():
    return workspace_manager.vscode_status()

@router.get("/recents")
async def get_recents():
    return {"recents": workspace_manager.get_recents()}

@router.post("/context/read")
async def read_context(req: OpenFileRequest):
    result = workspace_manager.read_file_context(req.file_path)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.post("/context/ask")
async def ask_with_context(req: FileContextRequest):
    prompt = workspace_manager.build_code_prompt(req.file_path, req.instruction)
    result = await router_engine.route(prompt, model_override="qwen2.5-coder:7b")
    return {"response": result["response"], "model": result["model"], "file": req.file_path}

@router.post("/tree")
async def file_tree(req: TreeRequest):
    result = workspace_manager.get_file_tree(req.root, req.max_depth)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.post("/assist")
async def code_assist(req: CodeRequest):
    lang_hint = f"Language: {req.language}\n\n" if req.language else ""
    prompt    = f"{req.instruction}\n\n{lang_hint}```{req.language or ''}\n{req.code}\n```"
    model     = req.model or "qwen2.5-coder:7b"
    result    = await router_engine.route(prompt, model_override=model)
    return {"response": result["response"], "model": result["model"], "task_type": "code"}
