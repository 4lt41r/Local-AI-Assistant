"""
installer/install_voice.py — Download Whisper.cpp + Piper + models
Fixed: updated Piper URL (v1.2.0 removed, now uses latest release API)
"""

import hashlib
import os
import shutil
import sys
import urllib.request
import json
import zipfile
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
VOICE_DIR    = INSTALL_ROOT / "voice"
WHISPER_DIR  = VOICE_DIR / "whisper"
PIPER_DIR    = VOICE_DIR / "piper"
LOGS_DIR     = INSTALL_ROOT / "logs"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

# ── Whisper.cpp ───────────────────────────────────────────────
# Prebuilt Windows x64 binary from whisper.cpp releases
WHISPER_BIN_URL   = "https://github.com/ggerganov/whisper.cpp/releases/download/v1.7.1/whisper-bin-x64.zip"
WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"

# ── Piper ─────────────────────────────────────────────────────
# Use GitHub API to get the actual latest release asset URL
PIPER_API_URL    = "https://api.github.com/repos/rhasspy/piper/releases/latest"
PIPER_VOICE_URL  = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
    "en/en_US/lessac/medium/en_US-lessac-medium.onnx"
)
PIPER_JSON_URL   = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
    "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
)


def progress_hook(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb  = downloaded / 1e6
        tot = total_size / 1e6
        print(f"\r  [{pct:3d}%] {mb:.1f} / {tot:.1f} MB", end="", flush=True)


def download(url: str, dest: Path, label: str) -> bool:
    print(f"\n  {CYAN}Downloading {label}{RESET}")
    print(f"  {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Installer/1.0"})
        with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
            total   = int(resp.headers.get("Content-Length", 0))
            written = 0
            block   = 8192
            while True:
                chunk = resp.read(block)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
                if total:
                    pct = min(100, written * 100 // total)
                    print(f"\r  [{pct:3d}%] {written/1e6:.1f} / {total/1e6:.1f} MB",
                          end="", flush=True)
        print(f"\n  {GREEN}✓ {dest.name}{RESET}")
        return True
    except Exception as e:
        print(f"\n  {RED}✗ Failed: {e}{RESET}")
        return False


def get_piper_download_url() -> str:
    """Fetch latest Piper release URL from GitHub API."""
    print(f"  Fetching latest Piper release info...")
    try:
        req  = urllib.request.Request(
            PIPER_API_URL,
            headers={"User-Agent": "JARVIS-Installer/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data   = json.loads(resp.read())
            assets = data.get("assets", [])
            # Look for windows amd64 zip
            for asset in assets:
                name = asset["name"].lower()
                if "windows" in name and "amd64" in name and name.endswith(".zip"):
                    url = asset["browser_download_url"]
                    print(f"  Found: {asset['name']}")
                    return url
            # Fallback: return first zip asset
            for asset in assets:
                if asset["name"].endswith(".zip"):
                    return asset["browser_download_url"]
    except Exception as e:
        print(f"  {YELLOW}API lookup failed: {e} — using fallback URL{RESET}")

    # Hard fallback to a known working version
    return "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"


def extract_zip(zip_path: Path, dest: Path):
    print(f"  Extracting → {dest.name}/")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(str(dest))
    zip_path.unlink()


def install_whisper() -> bool:
    print(f"\n{YELLOW}  Installing Whisper.cpp{RESET}")
    WHISPER_DIR.mkdir(parents=True, exist_ok=True)

    exe = WHISPER_DIR / "whisper.exe"
    if exe.exists():
        print(f"  {GREEN}✓ Whisper binary already present{RESET}")
    else:
        zip_path = WHISPER_DIR / "whisper-bin.zip"
        if not download(WHISPER_BIN_URL, zip_path, "whisper.cpp binary"):
            return False
        extract_zip(zip_path, WHISPER_DIR)

        # Rename main binary if needed
        for pattern in ["whisper-cli.exe", "main.exe", "whisper.exe"]:
            found = list(WHISPER_DIR.rglob(pattern))
            if found:
                target = WHISPER_DIR / "whisper.exe"
                if found[0] != target:
                    shutil.move(str(found[0]), str(target))
                break

    model_path = WHISPER_DIR / "ggml-base.en.bin"
    if model_path.exists():
        print(f"  {GREEN}✓ Whisper model already present{RESET}")
    else:
        if not download(WHISPER_MODEL_URL, model_path, "Whisper base.en model (~150MB)"):
            return False

    print(f"  {GREEN}✓ Whisper ready{RESET}")
    return True


def install_piper() -> bool:
    print(f"\n{YELLOW}  Installing Piper TTS{RESET}")
    PIPER_DIR.mkdir(parents=True, exist_ok=True)

    exe = PIPER_DIR / "piper.exe"
    if exe.exists():
        print(f"  {GREEN}✓ Piper binary already present{RESET}")
    else:
        piper_url = get_piper_download_url()
        zip_path  = PIPER_DIR / "piper.zip"
        if not download(piper_url, zip_path, "Piper TTS binary"):
            return False
        extract_zip(zip_path, PIPER_DIR)

        # Flatten nested piper/ subfolder if present
        nested = PIPER_DIR / "piper"
        if nested.exists() and nested.is_dir():
            for f in nested.iterdir():
                dest = PIPER_DIR / f.name
                if not dest.exists():
                    shutil.move(str(f), str(dest))
            try:
                nested.rmdir()
            except Exception:
                pass

    # Voice model
    onnx = PIPER_DIR / "en_US-lessac-medium.onnx"
    jsn  = PIPER_DIR / "en_US-lessac-medium.onnx.json"

    if not onnx.exists():
        if not download(PIPER_VOICE_URL, onnx, "Piper voice model (~60MB)"):
            return False
    else:
        print(f"  {GREEN}✓ Piper voice model already present{RESET}")

    if not jsn.exists():
        if not download(PIPER_JSON_URL, jsn, "Piper voice config"):
            return False

    print(f"  {GREEN}✓ Piper ready{RESET}")
    return True


def main():
    LOGS_DIR.mkdir(exist_ok=True)
    print(f"\n{YELLOW}  JARVIS Voice Installer{RESET}")

    w = install_whisper()
    p = install_piper()

    print(f"\n  {'─' * 40}")
    print(f"  Whisper: {GREEN+'OK'+RESET if w else RED+'FAILED'+RESET}")
    print(f"  Piper:   {GREEN+'OK'+RESET if p else RED+'FAILED'+RESET}")
    print()

    if not (w and p):
        print(f"  {YELLOW}Voice partially failed.")
        print(f"  JARVIS will still work — voice features will be limited.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
