"""
backend/services/memory_service.py — Persistent user profile + conversation history.

Profile  : config/user_profile.json   (name, location, preferences, facts)
History  : config/conversations/<session_id>.json  (role, content, timestamp)

Auto-extracts name/location from conversation so JARVIS learns as you talk.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from config import INSTALL_ROOT

log = logging.getLogger("jarvis.memory")

PROFILE_PATH  = INSTALL_ROOT / "config" / "user_profile.json"
CONV_DIR      = INSTALL_ROOT / "config" / "conversations"
MAX_STORED    = 200   # messages kept on disk per session
MAX_CONTEXT   = 20    # messages sent to the model per request


class MemoryService:

    def __init__(self):
        CONV_DIR.mkdir(parents=True, exist_ok=True)
        self._profile: dict = self._load_profile()

    # ── User profile ───────────────────────────────────────────────
    def _load_profile(self) -> dict:
        if PROFILE_PATH.exists():
            try:
                return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"name": None, "location": None, "preferences": {}, "facts": []}

    def _save_profile(self):
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(
            json.dumps(self._profile, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_profile(self) -> dict:
        return dict(self._profile)

    def update_profile(self, key: str, value):
        self._profile[key] = value
        self._save_profile()
        log.info(f"Profile updated: {key} = {value!r}")

    def add_preference(self, key: str, value: str):
        self._profile.setdefault("preferences", {})[key] = value
        self._save_profile()
        log.info(f"Preference saved: {key} = {value!r}")

    def add_fact(self, fact: str):
        facts = self._profile.setdefault("facts", [])
        if fact not in facts:
            facts.append(fact)
            if len(facts) > 20:
                facts.pop(0)
            self._save_profile()

    def get_system_context(self) -> str:
        """One-paragraph context block injected into every system prompt."""
        parts = []
        if self._profile.get("name"):
            parts.append(f"The user's name is {self._profile['name']}.")
        if self._profile.get("location"):
            parts.append(f"They are based in {self._profile['location']}.")
        if self._profile.get("preferences"):
            prefs = "; ".join(
                f"{k}: {v}" for k, v in self._profile["preferences"].items()
            )
            parts.append(f"User preferences — {prefs}.")
        if self._profile.get("facts"):
            facts_str = " ".join(self._profile["facts"][:5])
            parts.append(f"Additional context: {facts_str}")
        if not parts:
            return ""
        return "About the user: " + " ".join(parts)

    # ── Auto-extraction from speech/text ──────────────────────────
    def extract_profile_facts(self, text: str):
        """Parse user message for name, location, and explicit remember commands."""
        self._try_extract_name(text)
        self._try_extract_location(text)
        self._try_extract_remember(text)
        self._try_extract_preference(text)

    def _try_extract_name(self, text: str):
        patterns = [
            r"\bmy name is ([A-Za-z][a-z]+(?: [A-Za-z][a-z]+)?)\b",
            r"\bcall me ([A-Za-z][a-z]+)\b",
            r"\bpeople call me ([A-Za-z][a-z]+)\b",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip().title()
                if name and self._profile.get("name") != name:
                    self.update_profile("name", name)
                return

    def _try_extract_location(self, text: str):
        patterns = [
            r"\bi(?:'m| am) from ([A-Za-z][a-zA-Z ,]+?)(?:\.|,| and\b|$)",
            r"\bi live in ([A-Za-z][a-zA-Z ,]+?)(?:\.|,| and\b|$)",
            r"\bi(?:'m| am) based in ([A-Za-z][a-zA-Z ,]+?)(?:\.|,| and\b|$)",
            r"\bmy (?:city|home|location) is ([A-Za-z][a-zA-Z ,]+?)(?:\.|,| and\b|$)",
            r"\bi(?:'m| am) currently in ([A-Za-z][a-zA-Z ,]+?)(?:\.|,| and\b|$)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                loc = m.group(1).strip().rstrip(".,").title()
                if loc and len(loc) < 60 and self._profile.get("location") != loc:
                    self.update_profile("location", loc)
                return

    def _try_extract_remember(self, text: str):
        m = re.search(r"\bremember (?:that )?(.+)", text, re.IGNORECASE)
        if m:
            fact = m.group(1).strip().rstrip(".")
            if fact:
                self.add_fact(fact)
                log.info(f"Remembered: {fact!r}")

    def _try_extract_preference(self, text: str):
        patterns = [
            (r"\bi prefer ([^.!?]+)", "preference"),
            (r"\bi(?:'d| would) like ([^.!?]+) responses", "response_style"),
            (r"\bkeep (?:your )?(?:answers?|responses?) ([^.!?]+)", "response_style"),
        ]
        for p, key in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                value = m.group(1).strip().rstrip(".,")
                if value:
                    self.add_preference(key, value)

    # ── Conversation history ───────────────────────────────────────
    def _conv_path(self, session_id: str) -> Path:
        safe = re.sub(r"[^\w\-]", "_", session_id)[:80]
        return CONV_DIR / f"{safe}.json"

    def _load_conv(self, session_id: str) -> list:
        path = self._conv_path(session_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_conv(self, session_id: str, messages: list):
        path = self._conv_path(session_id)
        # Cap stored size
        if len(messages) > MAX_STORED:
            messages = messages[-MAX_STORED:]
        path.write_text(
            json.dumps(messages, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_history(self, session_id: str, limit: int = MAX_CONTEXT) -> list:
        msgs = self._load_conv(session_id)
        return msgs[-limit:] if len(msgs) > limit else msgs

    def add_turn(self, session_id: str, role: str, content: str):
        msgs = self._load_conv(session_id)
        msgs.append({"role": role, "content": content, "ts": int(time.time())})
        self._save_conv(session_id, msgs)
        if role == "user":
            self.extract_profile_facts(content)

    def clear_history(self, session_id: str):
        path = self._conv_path(session_id)
        if path.exists():
            path.unlink()
        log.info(f"Cleared conversation: {session_id}")

    def build_prompt(self, session_id: str, new_message: str, system: str) -> str:
        """Format history + user context + new message for Ollama /api/generate."""
        history = self.get_history(session_id)
        ctx = self.get_system_context()
        if ctx:
            system = f"{system}\n\n{ctx}"
        parts = [f"System: {system}\n"]
        for msg in history:
            prefix = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{prefix}: {msg['content']}")
        parts.append(f"User: {new_message}")
        parts.append("Assistant:")
        return "\n".join(parts)


# Singleton
memory_service = MemoryService()
