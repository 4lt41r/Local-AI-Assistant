"""
installer/install_vscode.py — Download VS Code portable + configure Continue.dev
Installs to JARVIS/vscode/ in fully portable mode (no system registry)
"""

import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR   = INSTALL_ROOT / "vscode"
DATA_DIR     = VSCODE_DIR / "data"           # portable mode marker
EXT_DIR      = DATA_DIR / "extensions"
USER_DIR     = DATA_DIR / "user-data"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

# VS Code portable Windows x64
VSCODE_URL = (
    "https://update.code.visualstudio.com/latest/win32-x64-archive/stable"
)


def progress_hook(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb  = downloaded / 1e6
        tot = total_size / 1e6
        print(f"\r  [{pct:3d}%] {mb:.1f} / {tot:.1f} MB", end="", flush=True)


def download_vscode() -> bool:
    print(f"\n{YELLOW}  Downloading VS Code portable{RESET}")
    zip_path = INSTALL_ROOT / "vscode.zip"
    try:
        urllib.request.urlretrieve(VSCODE_URL, str(zip_path), reporthook=progress_hook)
        print(f"\n  {GREEN}✓ Downloaded{RESET}")
    except Exception as e:
        print(f"\n  {RED}✗ Download failed: {e}{RESET}")
        return False

    print(f"  Extracting to {VSCODE_DIR}/...")
    VSCODE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(str(VSCODE_DIR))
        zip_path.unlink()
    except Exception as e:
        print(f"  {RED}✗ Extract failed: {e}{RESET}")
        return False

    # Enable portable mode: create data/ directory
    DATA_DIR.mkdir(exist_ok=True)
    print(f"  {GREEN}✓ VS Code portable ready{RESET}")
    return True


def configure_settings():
    """Write sensible default settings for JARVIS workflow."""
    settings_dir = USER_DIR / "User"
    settings_dir.mkdir(parents=True, exist_ok=True)

    settings = {
        "editor.fontSize": 14,
        "editor.fontFamily": "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
        "editor.fontLigatures": True,
        "editor.formatOnSave": True,
        "editor.minimap.enabled": False,
        "editor.wordWrap": "on",
        "editor.tabSize": 4,
        "workbench.colorTheme": "Default Dark+",
        "workbench.startupEditor": "none",
        "terminal.integrated.defaultProfile.windows": "Command Prompt",
        "extensions.autoUpdate": False,   # offline — no auto-update
        "telemetry.telemetryLevel": "off",
        "update.mode": "none",
        # Continue.dev integration
        "continue.enableTabAutocomplete": True,
        "continue.showInlineTip": True,
    }

    path = settings_dir / "settings.json"
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"  {GREEN}✓ VS Code settings configured{RESET}")


def configure_continue_dev():
    """Write Continue.dev config pointing to local Ollama."""
    config_dir = Path.home() / ".continue"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.json"

    # Don't overwrite existing config
    if config_path.exists():
        print(f"  {YELLOW}  Continue.dev config already exists — skipping{RESET}")
        return

    config = {
        "models": [
            {
                "title":    "JARVIS Coder",
                "provider": "ollama",
                "model":    "qwen2.5-coder:7b",
                "apiBase":  "http://localhost:11434",
            },
            {
                "title":    "JARVIS General",
                "provider": "ollama",
                "model":    "llama3.1:8b",
                "apiBase":  "http://localhost:11434",
            },
            {
                "title":    "JARVIS Reasoner",
                "provider": "ollama",
                "model":    "deepseek-r1:7b",
                "apiBase":  "http://localhost:11434",
            },
        ],
        "tabAutocompleteModel": {
            "title":    "Autocomplete",
            "provider": "ollama",
            "model":    "qwen2.5-coder:7b",
            "apiBase":  "http://localhost:11434",
        },
        "allowAnonymousTelemetry": False,
        "embeddingsProvider": {
            "provider": "ollama",
            "model":    "nomic-embed-text",
            "apiBase":  "http://localhost:11434",
        },
    }

    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"  {GREEN}✓ Continue.dev configured → {config_path}{RESET}")


def write_workspace_file():
    """Create JARVIS.code-workspace for quick project open."""
    ws = {
        "folders": [
            {"path": str(INSTALL_ROOT), "name": "JARVIS Root"},
            {"path": str(INSTALL_ROOT / "backend"), "name": "Backend"},
            {"path": str(INSTALL_ROOT / "launcher"), "name": "Launcher"},
        ],
        "settings": {
            "python.defaultInterpreterPath": str(
                INSTALL_ROOT / "venv" / "Scripts" / "python.exe"
            ),
        },
    }
    ws_path = INSTALL_ROOT / "JARVIS.code-workspace"
    ws_path.write_text(json.dumps(ws, indent=2), encoding="utf-8")
    print(f"  {GREEN}✓ Workspace file: {ws_path.name}{RESET}")


def main():
    print(f"\n{YELLOW}  JARVIS VS Code Installer{RESET}")

    code_exe = VSCODE_DIR / "Code.exe"
    if code_exe.exists():
        print(f"  {GREEN}VS Code already installed at {code_exe}{RESET}")
    else:
        if not download_vscode():
            sys.exit(1)

    configure_settings()
    configure_continue_dev()
    write_workspace_file()

    print(f"\n  {GREEN}VS Code portable ready.{RESET}")
    print(f"  Launch: {code_exe}")
    print(f"  Install Continue.dev extension inside VS Code for AI assistance.\n")


if __name__ == "__main__":
    main()
