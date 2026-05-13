"""
backend/services/workspace_manager.py — Project workspace management
Handles:
- Recent projects list
- Open folder in VS Code portable
- File context extraction for AI
- Project file tree
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from config import INSTALL_ROOT, settings

log = logging.getLogger("jarvis.workspace")

VSCODE_EXE    = INSTALL_ROOT / "vscode" / "Code.exe"
RECENTS_FILE  = INSTALL_ROOT / "config" / "recent_projects.json"

# Max file size to read for AI context (bytes)
MAX_FILE_SIZE = 64 * 1024   # 64KB


class WorkspaceManager:

    def __init__(self):
        self._recents: list[dict] = []
        self._load_recents()

    # ── VS Code ───────────────────────────────────────────────────
    def open_in_vscode(self, path: str = "") -> dict:
        """Launch VS Code portable with optional path."""
        if not VSCODE_EXE.exists():
            return {
                "error": f"VS Code not found at {VSCODE_EXE}. Run install_vscode.py."
            }

        target = path or str(INSTALL_ROOT)
        args   = [str(VSCODE_EXE), target]

        try:
            subprocess.Popen(
                args,
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._add_recent(target)
            log.info(f"Launched VS Code: {target}")
            return {"status": "launched", "path": target}
        except Exception as e:
            log.error(f"VS Code launch error: {e}")
            return {"error": str(e)}

    def open_file_in_vscode(self, file_path: str, line: int = 1) -> dict:
        """Open specific file at a line: code --goto path:line"""
        if not VSCODE_EXE.exists():
            return {"error": "VS Code not installed"}
        target = f"{file_path}:{line}"
        try:
            subprocess.Popen(
                [str(VSCODE_EXE), "--goto", target],
                close_fds=True,
            )
            return {"status": "launched", "file": file_path, "line": line}
        except Exception as e:
            return {"error": str(e)}

    def vscode_status(self) -> dict:
        return {
            "installed": VSCODE_EXE.exists(),
            "path":      str(VSCODE_EXE),
        }

    # ── File context for AI ───────────────────────────────────────
    def read_file_context(self, file_path: str) -> dict:
        """Read file content for injection into AI prompt."""
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if p.stat().st_size > MAX_FILE_SIZE:
            return {"error": f"File too large (>{MAX_FILE_SIZE//1024}KB)"}

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return {
                "path":      str(p),
                "name":      p.name,
                "extension": p.suffix,
                "content":   content,
                "lines":     content.count("\n") + 1,
                "size_kb":   round(p.stat().st_size / 1024, 1),
            }
        except Exception as e:
            return {"error": str(e)}

    def build_code_prompt(self, file_path: str, instruction: str) -> str:
        """Build a prompt with file context for AI."""
        ctx = self.read_file_context(file_path)
        if "error" in ctx:
            return instruction

        lang = self._detect_language(ctx["extension"])
        return (
            f"{instruction}\n\n"
            f"File: `{ctx['name']}` ({ctx['lines']} lines)\n\n"
            f"```{lang}\n{ctx['content']}\n```"
        )

    @staticmethod
    def _detect_language(ext: str) -> str:
        return {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".rs": "rust",   ".go": "go",         ".cpp": "cpp",
            ".c":  "c",      ".java": "java",      ".sh": "bash",
            ".md": "markdown", ".json": "json",    ".html": "html",
            ".css": "css",   ".sql": "sql",
        }.get(ext.lower(), "")

    # ── File tree ─────────────────────────────────────────────────
    def get_file_tree(self, root: str, max_depth: int = 3) -> dict:
        """Return directory tree as nested dict."""
        p = Path(root)
        if not p.exists() or not p.is_dir():
            return {"error": f"Directory not found: {root}"}
        return {"tree": self._tree(p, max_depth, 0)}

    def _tree(self, path: Path, max_depth: int, depth: int) -> dict:
        node = {"name": path.name, "type": "dir", "children": []}
        if depth >= max_depth:
            return node
        try:
            for child in sorted(path.iterdir()):
                if child.name.startswith(".") or child.name in {
                    "node_modules", "__pycache__", ".git", "venv", "dist",
                }:
                    continue
                if child.is_dir():
                    node["children"].append(self._tree(child, max_depth, depth + 1))
                else:
                    node["children"].append({
                        "name": child.name,
                        "type": "file",
                        "size_kb": round(child.stat().st_size / 1024, 1),
                    })
        except PermissionError:
            pass
        return node

    # ── Recent projects ───────────────────────────────────────────
    def _load_recents(self):
        try:
            if RECENTS_FILE.exists():
                self._recents = json.loads(RECENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._recents = []

    def _save_recents(self):
        RECENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECENTS_FILE.write_text(json.dumps(self._recents, indent=2), encoding="utf-8")

    def _add_recent(self, path: str):
        self._recents = [r for r in self._recents if r.get("path") != path]
        self._recents.insert(0, {"path": path, "name": Path(path).name})
        self._recents = self._recents[:10]   # keep last 10
        self._save_recents()

    def get_recents(self) -> list:
        return self._recents


# Singleton
workspace_manager = WorkspaceManager()
