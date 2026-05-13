"""
installer/install_ollama.py — Standalone Ollama installer
Downloads and installs Ollama for Windows, then starts service.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR   = INSTALL_ROOT / "models" / "ollama"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"

OLLAMA_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
)


def is_ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


def main():
    print(f"\n{YELLOW}  JARVIS — Ollama Installer{RESET}")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # Already installed?
    if shutil.which("ollama"):
        print(f"  {GREEN}✓ Ollama already in PATH{RESET}")
    else:
        installer = INSTALL_ROOT / "OllamaSetup.exe"
        print(f"  Downloading Ollama...")
        try:
            def hook(b, bs, tot):
                pct = min(100, b * bs * 100 // (tot or 1))
                print(f"\r  [{pct:3d}%]", end="", flush=True)
            urllib.request.urlretrieve(OLLAMA_URL, str(installer), reporthook=hook)
            print(f"\n  {GREEN}✓ Downloaded{RESET}")
        except Exception as e:
            print(f"\n  {RED}✗ Download failed: {e}{RESET}")
            sys.exit(1)

        print("  Installing Ollama...")
        try:
            subprocess.run([str(installer), "/S"], check=True, timeout=120)
            installer.unlink(missing_ok=True)
            print(f"  {GREEN}✓ Installed{RESET}")
        except Exception as e:
            print(f"  {RED}✗ Install failed: {e}{RESET}")
            sys.exit(1)

    # Start service
    if is_ollama_running():
        print(f"  {GREEN}✓ Ollama service already running{RESET}")
        return

    print("  Starting Ollama service...")
    exe = shutil.which("ollama")
    env = {
        **os.environ,
        "OLLAMA_MODELS":     str(MODELS_DIR),
        "OLLAMA_NUM_GPU":    "1",
        "OLLAMA_KEEP_ALIVE": "5m",
    }
    try:
        subprocess.Popen(
            [exe, "serve"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for _ in range(20):
            time.sleep(0.5)
            if is_ollama_running():
                print(f"  {GREEN}✓ Ollama service running on :11434{RESET}")
                return
        print(f"  {RED}✗ Ollama did not start in time{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Could not start Ollama: {e}{RESET}")


if __name__ == "__main__":
    main()
