"""
backend/services/tools_service.py — Local machine tool implementations.

Tools available to JARVIS:
  read_file, write_file, list_directory, search_files,
  run_command, web_search, web_fetch,
  get_system_info, open_file, get_clipboard, set_clipboard

Each tool returns a plain string result that gets fed back to the model.
Every execution is logged to logs/tool_calls.log (JSON lines).
"""

import asyncio
import fnmatch
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from config import INSTALL_ROOT

log = logging.getLogger("jarvis.tools")

TOOL_LOG = INSTALL_ROOT / "logs" / "tool_calls.log"
MAX_FILE_CHARS  = 12_000   # max chars returned from read_file
MAX_SEARCH_HITS = 25       # max files returned from search_files
MAX_WEB_CHARS   = 5_000    # max chars from web_fetch

# ── Safety blocklist for run_command ──────────────────────────────────────────
_BLOCKED = [
    r"\bformat\b.{0,10}[a-zA-Z]:",
    r"\bdiskpart\b",
    r"\brmdir\b.+/[sS]",
    r"\brd\b.+/[sS]",
    r"Remove-Item.{0,40}-Recurse.{0,40}-Force.{0,60}(?:C:|Windows|System32)",
    r"\bnet\s+user\b.+/add\b",
    r"\breg\s+delete\b",
    r"\bsc\s+delete\b",
    r"\bnetsh\b.+firewall\b.+delete\b",
]
_BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in _BLOCKED]


# ── JSON schemas exposed to Ollama ─────────────────────────────────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file on the local machine. "
                "Returns the file text, optionally limited to a line range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-indexed, optional).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read inclusive (optional).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or append text to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "content": {"type": "string", "description": "Text to write."},
                    "mode": {
                        "type": "string",
                        "enum": ["write", "append"],
                        "description": "'write' overwrites, 'append' adds to end. Default: write.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subfolders in a directory with sizes and types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path."},
                    "show_hidden": {
                        "type": "boolean",
                        "description": "Include hidden files. Default: false.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Recursively search for files by name pattern and/or content string. "
                "Use name_pattern like '*.py' or content_search to grep inside files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Root directory to search.",
                    },
                    "name_pattern": {
                        "type": "string",
                        "description": "Glob pattern for filename, e.g. '*.py', 'main*'.",
                    },
                    "content_search": {
                        "type": "string",
                        "description": "Text or regex to search inside files.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum files to return. Default: 25.",
                    },
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a PowerShell command on the local Windows machine. "
                "Returns stdout and stderr. Use for git, pip, npm, file operations, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "PowerShell command to execute.",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional, defaults to JARVIS root).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default: 30.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return. Default: 6.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and extract readable text content from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch."},
                    "max_chars": {
                        "type": "integer",
                        "description": f"Max characters to return. Default: {MAX_WEB_CHARS}.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get current system stats: CPU, RAM, disk usage, and optionally top processes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_processes": {
                        "type": "boolean",
                        "description": "Include top 10 running processes by CPU. Default: false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": "Open a file, folder, or URL in its default application (Explorer, browser, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path, folder path, or URL to open.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clipboard",
            "description": "Read the current clipboard contents.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_clipboard",
            "description": "Copy text to the clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to copy."},
                },
                "required": ["text"],
            },
        },
    },
]

# Map name → schema for quick lookup
TOOL_MAP = {s["function"]["name"]: s for s in TOOL_SCHEMAS}


# ── Tool service ───────────────────────────────────────────────────────────────
class ToolsService:

    def __init__(self):
        TOOL_LOG.parent.mkdir(parents=True, exist_ok=True)

    # ── Dispatcher ────────────────────────────────────────────────
    async def execute(self, name: str, args: dict) -> str:
        """Route a tool call by name, log it, return string result."""
        start = time.monotonic()
        try:
            result = await self._dispatch(name, args)
        except Exception as e:
            result = f"ERROR: {e}"
            log.error(f"Tool '{name}' raised: {e}")

        elapsed = time.monotonic() - start
        self._log(name, args, result, elapsed)
        log.info(f"[tool:{name}] completed in {elapsed:.2f}s")
        return result

    async def _dispatch(self, name: str, args: dict) -> str:
        loop = asyncio.get_event_loop()
        if name == "read_file":
            return await loop.run_in_executor(None, lambda: self._read_file(**args))
        if name == "write_file":
            return await loop.run_in_executor(None, lambda: self._write_file(**args))
        if name == "list_directory":
            return await loop.run_in_executor(None, lambda: self._list_directory(**args))
        if name == "search_files":
            return await loop.run_in_executor(None, lambda: self._search_files(**args))
        if name == "run_command":
            return await self._run_command(**args)
        if name == "web_search":
            return await self._web_search(**args)
        if name == "web_fetch":
            return await self._web_fetch(**args)
        if name == "get_system_info":
            return await loop.run_in_executor(None, lambda: self._get_system_info(**args))
        if name == "open_file":
            return await loop.run_in_executor(None, lambda: self._open_file(**args))
        if name == "get_clipboard":
            return await self._get_clipboard()
        if name == "set_clipboard":
            return await self._set_clipboard(**args)
        return f"Unknown tool: {name}"

    # ── read_file ─────────────────────────────────────────────────
    def _read_file(self, path: str, start_line: int = None, end_line: int = None) -> str:
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Read error: {e}"

        if start_line or end_line:
            lines = text.splitlines()
            s = (start_line or 1) - 1
            e = end_line or len(lines)
            text = "\n".join(lines[s:e])

        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + f"\n\n[...truncated at {MAX_FILE_CHARS} chars]"
        return text

    # ── write_file ────────────────────────────────────────────────
    def _write_file(self, path: str, content: str, mode: str = "write") -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        flag = "a" if mode == "append" else "w"
        try:
            p.open(flag, encoding="utf-8").write(content)
            return f"Written {len(content)} chars to {path} (mode={mode})"
        except Exception as e:
            return f"Write error: {e}"

    # ── list_directory ────────────────────────────────────────────
    def _list_directory(self, path: str, show_hidden: bool = False) -> str:
        p = Path(path)
        if not p.exists():
            return f"Path not found: {path}"
        if not p.is_dir():
            return f"Not a directory: {path}"
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            lines = [f"Directory: {p.resolve()}\n"]
            for entry in entries:
                if not show_hidden and entry.name.startswith("."):
                    continue
                kind = "DIR " if entry.is_dir() else "FILE"
                size = ""
                if entry.is_file():
                    try:
                        sz = entry.stat().st_size
                        size = f"  {sz:>10,} bytes" if sz < 1_000_000 else f"  {sz/1e6:>8.1f} MB"
                    except Exception:
                        pass
                lines.append(f"  [{kind}] {entry.name}{size}")
            return "\n".join(lines)
        except PermissionError:
            return f"Permission denied: {path}"

    # ── search_files ──────────────────────────────────────────────
    def _search_files(
        self,
        directory: str,
        name_pattern: str = None,
        content_search: str = None,
        max_results: int = MAX_SEARCH_HITS,
    ) -> str:
        root = Path(directory)
        if not root.exists():
            return f"Directory not found: {directory}"
        hits = []
        try:
            for p in root.rglob("*"):
                if len(hits) >= max_results:
                    break
                if not p.is_file():
                    continue
                # Skip common noise dirs
                parts = set(p.parts)
                if parts & {".git", "__pycache__", "node_modules", ".venv", "venv"}:
                    continue
                # Name filter
                if name_pattern and not fnmatch.fnmatch(p.name, name_pattern):
                    continue
                # Content filter
                if content_search:
                    try:
                        text = p.read_text(encoding="utf-8", errors="ignore")
                        if content_search.lower() not in text.lower():
                            continue
                        # Find first matching line
                        for i, line in enumerate(text.splitlines(), 1):
                            if content_search.lower() in line.lower():
                                hits.append(f"{p}:{i}  {line.strip()[:120]}")
                                break
                        continue
                    except Exception:
                        continue
                hits.append(str(p))
        except PermissionError:
            pass

        if not hits:
            return "No files found matching the criteria."
        total = len(hits)
        result = "\n".join(hits[:max_results])
        if total >= max_results:
            result += f"\n\n[Showing first {max_results} results]"
        return result

    # ── run_command ───────────────────────────────────────────────
    async def _run_command(
        self, command: str, working_dir: str = None, timeout: int = 30
    ) -> str:
        # Safety check
        for pattern in _BLOCKED_RE:
            if pattern.search(command):
                return f"BLOCKED: command matches safety blocklist — '{command[:80]}'"

        cwd = working_dir or str(INSTALL_ROOT)
        log.warning(f"[run_command] executing: {command[:200]}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return f"TIMEOUT: command exceeded {timeout}s"

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            rc  = proc.returncode

            parts = [f"Exit code: {rc}"]
            if out:
                parts.append(f"stdout:\n{out[:4000]}")
            if err:
                parts.append(f"stderr:\n{err[:1000]}")
            return "\n".join(parts) or f"Command completed (exit {rc}, no output)"

        except FileNotFoundError:
            return "ERROR: powershell.exe not found"
        except Exception as e:
            return f"ERROR: {e}"

    # ── web_search ────────────────────────────────────────────────
    async def _web_search(self, query: str, num_results: int = 6) -> str:
        # Try duckduckgo_search package first (pip install duckduckgo-search)
        try:
            from duckduckgo_search import DDGS
            loop = asyncio.get_event_loop()
            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=num_results))
            results = await loop.run_in_executor(None, _search)
            lines = []
            for r in results:
                lines.append(f"Title: {r.get('title', '')}")
                lines.append(f"URL:   {r.get('href', '')}")
                lines.append(f"      {r.get('body', '')}")
                lines.append("")
            return "\n".join(lines) or "No results."
        except ImportError:
            pass

        # Fallback: scrape DuckDuckGo lite HTML
        try:
            import httpx
            encoded = query.replace(" ", "+")
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            headers = {"User-Agent": "Mozilla/5.0 (compatible; JARVIS/1.0)"}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
            html = r.text
            # Extract result blocks
            titles   = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
            urls     = re.findall(r'class="result__url"[^>]*>\s*(.*?)\s*</[^>]+>', html, re.DOTALL)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            lines = []
            for i in range(min(num_results, len(titles))):
                title   = re.sub(r"<[^>]+>", "", titles[i]).strip()
                href    = urls[i].strip() if i < len(urls) else ""
                snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
                lines.append(f"Title: {title}")
                lines.append(f"URL:   {href}")
                lines.append(f"      {snippet}")
                lines.append("")
            return "\n".join(lines) or "No results (try installing: pip install duckduckgo-search)"
        except Exception as e:
            return f"Web search error: {e}"

    # ── web_fetch ─────────────────────────────────────────────────
    async def _web_fetch(self, url: str, max_chars: int = MAX_WEB_CHARS) -> str:
        try:
            import httpx
            headers = {"User-Agent": "Mozilla/5.0 (compatible; JARVIS/1.0)"}
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
            html = r.text
            # Strip scripts, styles, then tags
            html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = text.strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n[...truncated]"
            return text or "No readable content found."
        except Exception as e:
            return f"Fetch error: {e}"

    # ── get_system_info ───────────────────────────────────────────
    def _get_system_info(self, include_processes: bool = False) -> str:
        lines = []
        try:
            import psutil
            cpu   = psutil.cpu_percent(interval=0.5)
            ram   = psutil.virtual_memory()
            disks = psutil.disk_partitions()
            lines.append(f"CPU usage:  {cpu:.1f}%")
            lines.append(f"RAM:        {ram.used/1e9:.1f} GB used / {ram.total/1e9:.1f} GB total  ({ram.percent:.0f}%)")
            lines.append("")
            for disk in disks:
                try:
                    usage = psutil.disk_usage(disk.mountpoint)
                    lines.append(
                        f"Disk {disk.device}:  "
                        f"{usage.used/1e9:.1f} GB used / {usage.total/1e9:.1f} GB  "
                        f"({usage.percent:.0f}%)"
                    )
                except Exception:
                    pass
            if include_processes:
                procs = sorted(
                    psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]),
                    key=lambda p: p.info["cpu_percent"] or 0,
                    reverse=True,
                )
                lines.append("\nTop processes:")
                for p in procs[:10]:
                    mem_mb = (p.info["memory_info"].rss / 1e6) if p.info.get("memory_info") else 0
                    lines.append(
                        f"  {p.info['name']:<30} CPU={p.info['cpu_percent'] or 0:>5.1f}%  "
                        f"RAM={mem_mb:>7.1f} MB"
                    )
        except ImportError:
            # psutil not installed — use PowerShell fallback
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "Get-ComputerInfo | Select-Object CsProcessors,OsTotalVisibleMemorySize,OsFreePhysicalMemory | ConvertTo-Json"],
                    capture_output=True, text=True, timeout=10
                )
                lines.append(r.stdout.strip() or "System info unavailable")
            except Exception as e:
                lines.append(f"System info error: {e}")
        return "\n".join(lines)

    # ── open_file ─────────────────────────────────────────────────
    def _open_file(self, path: str) -> str:
        try:
            os.startfile(path)
            return f"Opened: {path}"
        except AttributeError:
            # Non-Windows fallback
            subprocess.Popen(["xdg-open", path])
            return f"Opened: {path}"
        except Exception as e:
            return f"Could not open '{path}': {e}"

    # ── clipboard ─────────────────────────────────────────────────
    async def _get_clipboard(self) -> str:
        try:
            import pyperclip
            text = pyperclip.paste()
            return text or "(clipboard is empty)"
        except ImportError:
            pass
        try:
            loop = asyncio.get_event_loop()
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-Command", "Get-Clipboard",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return out.decode("utf-8", errors="replace").strip() or "(clipboard is empty)"
        except Exception as e:
            return f"Clipboard read error: {e}"

    async def _set_clipboard(self, text: str) -> str:
        try:
            import pyperclip
            pyperclip.copy(text)
            return f"Copied {len(text)} chars to clipboard."
        except ImportError:
            pass
        try:
            escaped = text.replace("'", "''")
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-Command", f"Set-Clipboard -Value '{escaped}'",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return f"Copied {len(text)} chars to clipboard."
        except Exception as e:
            return f"Clipboard write error: {e}"

    # ── Audit log ─────────────────────────────────────────────────
    def _log(self, name: str, args: dict, result: str, elapsed: float):
        try:
            entry = {
                "ts":      int(time.time()),
                "tool":    name,
                "args":    {k: str(v)[:200] for k, v in args.items()},
                "elapsed": round(elapsed, 3),
                "result_len": len(result),
            }
            with TOOL_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


# Singleton
tools_service = ToolsService()
