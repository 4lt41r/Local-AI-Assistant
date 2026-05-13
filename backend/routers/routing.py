"""
backend/routers/routing.py — AI routing inspection and override endpoints
"""

import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from services.router_engine import router_engine
from services.task_classifier import task_classifier
from services.model_manager import model_manager

log = logging.getLogger("jarvis.routing")
router = APIRouter()


class ClassifyRequest(BaseModel):
    prompt: str


class RouteOverride(BaseModel):
    task_type: str   # code | reasoning | vision | general
    model: str


# ── Classify (dry run — no generation) ───────────────────────
@router.post("/classify")
async def classify_prompt(req: ClassifyRequest):
    """
    Classify a prompt without running inference.
    Returns task_type, confidence, scores, signals, and target model.
    """
    return router_engine.debug_classify(req.prompt)


# ── Routing table ─────────────────────────────────────────────
@router.get("/table")
async def routing_table():
    """Current routing: task → model mapping."""
    return model_manager.get_routing()


@router.post("/table")
async def update_routing_table(req: RouteOverride):
    """Override which model handles a task type."""
    return model_manager.update_routing(req.task_type, req.model)


# ── Test routing ──────────────────────────────────────────────
@router.post("/test")
async def test_routing(req: ClassifyRequest):
    """
    Classify + run inference, return routing metadata alongside response.
    Useful for verifying classifier accuracy.
    """
    result = await router_engine.route(req.prompt)
    return result
