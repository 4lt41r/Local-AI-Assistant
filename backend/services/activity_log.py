"""In-memory activity feed for the JARVIS dashboard."""
import time
from typing import Optional

_events: list = []
_MAX = 120


def log_event(event_type: str, message: str, detail: Optional[str] = None):
    _events.append({
        "ts":     time.time(),
        "type":   event_type,
        "msg":    message,
        "detail": detail,
    })
    if len(_events) > _MAX:
        _events.pop(0)


def get_recent(n: int = 30) -> list:
    return list(_events[-n:])
