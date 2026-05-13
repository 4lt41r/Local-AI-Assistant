"""
installer/install.py — JARVIS Master Installer
Fixed:
  - venv Access Denied (Program Files) → --without-pip + ensurepip
  - npm not found → search common Node.js paths before failing
  - charmap codec error → force UTF-8 on all subprocess output
  - Piper 404 → install_voice.py now uses GitHub API for URL
"""

import argparse
import json
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Force UTF-8 output on Windows to avoid charmap errors
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Paths ─────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
INSTALL_ROOT = SCRIPT_DIR.parent
VENV_DIR     = INSTALL_ROOT / "venv"
CONFIG_DIR   = INSTALL_ROOT / "config"
LOGS_DIR     = INSTALL_ROOT / "logs"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def h(msg):   print(f"\n{BOLD}{YELLOW}  {msg}{RESET}")
def ok(msg):  print(f"  {GREEN}✓  {msg}{RESET}")
def err(msg): print(f"  {RED}✗  {msg}{RESET}")
def info(msg):print(f"  {DIM}   {msg}{RESET}")
def sep():    print(f"  {'─' * 50}")


# ═══════════════════════════════════════════════════════════════
#  STEP 1 — System checks
# ═══════════════════════════════════════════════════════════════
def check_system() -> bool:
    h("STEP 1 — System checks")
    all_ok = True

    if platform.system() != "Windows":
        err(f"Windows required (detected {platform.system()})")
        all_ok = False
    else:
        ok(f"OS: {platform.system()} {platform.release()}")

    pv = sys.version_info
    if pv < (3, 11):
        err(f"Python 3.11+ required (found {pv.major}.{pv.minor})")
        all_ok = False
    else:
        ok(f"Python {pv.major}.{pv.minor}.{pv.micro}")

    # Node — search common locations
    node = _find_node()
    if not node:
        info("Node.js not found in PATH — will download portable version")
    else:
        try:
            ver   = subprocess.check_output([node, "--version"],
                        text=True, stderr=subprocess.DEVNULL).strip()
            major = int(ver.lstrip("v").split(".")[0])
            if major < 18:
                err(f"Node.js 18+ required (found {ver})")
                all_ok = False
            else:
                ok(f"Node.js {ver}")
        except Exception:
            info("Node.js version check failed — will verify in Step 6")

    try:
        usage   = shutil.disk_usage(INSTALL_ROOT)
        free_gb = usage.free / 1e9
        if free_gb < 15:
            err(f"Low disk space: {free_gb:.1f} GB free (need ~20 GB)")
            all_ok = False
        else:
            ok(f"Disk: {free_gb:.1f} GB free")
    except Exception:
        info("Could not check disk space")

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            timeout=5, stderr=subprocess.DEVNULL, text=True
        ).strip()
        ok(f"GPU: {out}")
    except Exception:
        info("NVIDIA GPU not detected (CPU mode — models will be slower)")

    return all_ok


# ═══════════════════════════════════════════════════════════════
#  STEP 2 — Python venv
# ═══════════════════════════════════════════════════════════════
def setup_python_env() -> bool:
    h("STEP 2 — Python virtual environment")

    req_file   = INSTALL_ROOT / "backend" / "requirements.txt"
    python_exe = _find_python()
    info(f"Using Python: {python_exe}")

    # ── Create venv ───────────────────────────────────────────
    if not (VENV_DIR / "Scripts" / "python.exe").exists():
        info(f"Creating venv at {VENV_DIR} ...")
        VENV_DIR.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [python_exe, "-m", "venv", str(VENV_DIR)],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            # Access Denied from Program Files → use --without-pip
            info("Standard venv failed — retrying with --without-pip ...")
            result2 = subprocess.run(
                [python_exe, "-m", "venv", "--without-pip", str(VENV_DIR)],
                capture_output=True, text=True
            )
            if result2.returncode != 0:
                err(f"venv creation failed: {result2.stderr.strip()}")
                err("Run this script as Administrator once to create the venv.")
                return False

            info("Bootstrapping pip ...")
            subprocess.run(
                [str(VENV_DIR / "Scripts" / "python.exe"),
                 "-m", "ensurepip", "--upgrade"],
                capture_output=True
            )

        ok("Virtual environment created")
    else:
        ok("Virtual environment already exists")

    pip = str(VENV_DIR / "Scripts" / "pip.exe")
    subprocess.run([pip, "install", "--quiet", "--upgrade", "pip"],
                   capture_output=True)

    if not req_file.exists():
        err(f"requirements.txt not found at {req_file}")
        return False

    info("Installing Python dependencies ...")
    result = subprocess.run(
        [pip, "install", "--quiet", "-r", str(req_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        err(f"pip install failed: {result.stderr.strip()[:300]}")
        return False

    ok("Python dependencies installed")
    return True


# ═══════════════════════════════════════════════════════════════
#  STEP 3 — Ollama
# ═══════════════════════════════════════════════════════════════
OLLAMA_INSTALLER_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
)

def install_ollama() -> bool:
    h("STEP 3 — Ollama")

    if shutil.which("ollama") or (INSTALL_ROOT / "ollama" / "ollama.exe").exists():
        ok("Ollama already installed")
        return _start_ollama()

    installer = INSTALL_ROOT / "ollama_setup.exe"
    info("Downloading Ollama installer ...")
    try:
        def hook(b, bs, tot):
            pct = min(100, b * bs * 100 // (tot or 1))
            print(f"\r  [{pct:3d}%]", end="", flush=True)
        urllib.request.urlretrieve(OLLAMA_INSTALLER_URL, str(installer), reporthook=hook)
        print()
        ok("Downloaded OllamaSetup.exe")
    except Exception as e:
        err(f"Download failed: {e}")
        return False

    info("Installing Ollama silently ...")
    try:
        subprocess.run([str(installer), "/S"], check=True, timeout=120)
        installer.unlink(missing_ok=True)
        ok("Ollama installed")
    except Exception as e:
        err(f"Install failed: {e}")
        return False

    return _start_ollama()


def _start_ollama() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        ok("Ollama service already running")
        return True
    except Exception:
        pass

    info("Starting Ollama service ...")
    exe = shutil.which("ollama") or str(INSTALL_ROOT / "ollama" / "ollama.exe")
    env = {
        **os.environ,
        "OLLAMA_MODELS":     str(INSTALL_ROOT / "models" / "ollama"),
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
            try:
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
                ok("Ollama service started")
                return True
            except Exception:
                pass
        err("Ollama did not respond in time")
        return False
    except Exception as e:
        err(f"Could not start Ollama: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  STEP 4 — AI models
# ═══════════════════════════════════════════════════════════════
def pull_models(skip: bool) -> bool:
    h("STEP 4 — AI models")
    if skip:
        info("Skipping (--skip-models). Run later: python installer/install_models.py")
        return True

    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from install_models import pull_model, MODELS
        results = []
        for name, desc in MODELS:
            results.append(pull_model(name, desc))
        return all(results)
    except Exception as e:
        err(f"Model install error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  STEP 5 — Voice
# ═══════════════════════════════════════════════════════════════
def install_voice(skip: bool) -> bool:
    h("STEP 5 — Voice (Whisper + Piper)")
    if skip:
        info("Skipping (--skip-voice)")
        return True
    try:
        from install_voice import install_whisper, install_piper
        w = install_whisper()
        p = install_piper()
        if not (w and p):
            info("Voice partial failure — JARVIS still works without voice")
        return True   # non-fatal
    except Exception as e:
        err(f"Voice install error: {e}")
        info("Continuing — voice is optional")
        return True   # non-fatal


# ═══════════════════════════════════════════════════════════════
#  STEP 6 — Electron / Node.js
# ═══════════════════════════════════════════════════════════════
def setup_electron() -> bool:
    h("STEP 6 — Electron (Node.js dependencies)")

    launcher_dir = INSTALL_ROOT / "launcher"
    pkg_json     = launcher_dir / "package.json"
    if not pkg_json.exists():
        err(f"package.json not found at {pkg_json}")
        return False

    if (launcher_dir / "node_modules" / "electron").exists():
        ok("node_modules already installed")
        return True

    # Find npm
    npm = _find_npm()
    if not npm:
        # Download portable Node.js
        info("npm not found — downloading portable Node.js ...")
        if not _download_node():
            err("Could not obtain Node.js. Install from https://nodejs.org (LTS)")
            return False
        npm = _find_npm()
        if not npm:
            err("npm still not found after Node.js download")
            return False

    info(f"Running npm install with: {npm}")
    try:
        result = subprocess.run(
            [npm, "install", "--prefer-offline"],
            cwd=str(launcher_dir),
            timeout=300,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err(f"npm install failed:\n{result.stderr.strip()[:500]}")
            return False
        ok("Electron dependencies installed")
        return True
    except FileNotFoundError:
        err(f"npm executable not found at: {npm}")
        return False
    except Exception as e:
        err(f"npm install error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  STEP 7 — VS Code
# ═══════════════════════════════════════════════════════════════
def install_vscode(skip: bool) -> bool:
    h("STEP 7 — VS Code portable")
    if skip:
        info("Skipping (--skip-vscode)")
        return True

    if (INSTALL_ROOT / "vscode" / "Code.exe").exists():
        ok("VS Code already installed")
        return True

    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from install_vscode import main as vscode_main
        vscode_main()
        return True
    except Exception as e:
        err(f"VS Code install failed: {e}")
        info("VS Code is optional — skipping")
        return True   # non-fatal


# ═══════════════════════════════════════════════════════════════
#  STEP 8 — Config
# ═══════════════════════════════════════════════════════════════
def generate_config() -> bool:
    h("STEP 8 — Configuration")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    (INSTALL_ROOT / "models" / "ollama").mkdir(parents=True, exist_ok=True)

    config_path = CONFIG_DIR / "jarvis.json"
    if config_path.exists():
        ok("jarvis.json already exists")
        return True

    config = {
        "version":           "1.0.0",
        "install_root":      str(INSTALL_ROOT),
        "backend_port":      8000,
        "electron_port":     3000,
        "ollama_host":       "http://localhost:11434",
        "ollama_keep_alive": "5m",
        "default_model":     "llama3.1:8b",
        "models": {
            "code":      "qwen2.5-coder:7b",
            "reasoning": "deepseek-r1:7b",
            "general":   "llama3.1:8b",
            "vision":    "llava:7b",
        },
        "voice": {
            "wake_word":      "hey jarvis",
            "whisper_model":  "base.en",
            "piper_voice":    "en_US-lessac-medium",
            "enabled":        True,
        },
        "gpu": {"num_gpu": 1, "vram_limit_gb": 4.0},
    }

    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    ok(f"jarvis.json written")
    return True


# ═══════════════════════════════════════════════════════════════
#  STEP 9 — Health check
# ═══════════════════════════════════════════════════════════════
def run_health_check() -> bool:
    h("STEP 9 — Health check")

    python  = str(VENV_DIR / "Scripts" / "python.exe")
    start   = str(INSTALL_ROOT / "scripts" / "start_backend.py")

    if not Path(python).exists():
        err("venv python not found — skipping backend health check")
        return False

    proc = subprocess.Popen(
        [python, start],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    backend_ok = False
    for _ in range(24):
        time.sleep(0.5)
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            backend_ok = True
            break
        except Exception:
            pass

    if backend_ok:
        ok("Backend responds on :8000")
    else:
        err("Backend did not start — check logs/")

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        ok("Ollama responds on :11434")
        ollama_ok = True
    except Exception:
        err("Ollama not responding")
        ollama_ok = False

    proc.terminate()
    return backend_ok and ollama_ok


# ═══════════════════════════════════════════════════════════════
#  STEP 10 — Launch
# ═══════════════════════════════════════════════════════════════
def launch_jarvis(no_launch: bool):
    h("STEP 10 — Launch JARVIS")
    if no_launch:
        info("Skipping launch (--no-launch)")
        info(f"To start: scripts\\start.bat")
        return
    launcher_dir = INSTALL_ROOT / "launcher"
    npm = _find_npm()
    if not npm:
        info("npm not found — launch manually: scripts\\start.bat")
        return
    try:
        subprocess.Popen([npm, "start"], cwd=str(launcher_dir))
        ok("JARVIS launched")
    except Exception as e:
        err(f"Launch failed: {e}")
        info("Manual start: scripts\\start.bat")


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════
def _find_python() -> str:
    """Find Python 3.11+ preferring non-Program Files locations."""
    candidates = []

    # Check registry
    try:
        import winreg
        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for base in [r"Software\Python\PythonCore"]:
                try:
                    with winreg.OpenKey(hive, base) as k:
                        i = 0
                        while True:
                            try:
                                ver = winreg.EnumKey(k, i)
                                with winreg.OpenKey(k, ver + r"\InstallPath") as ip:
                                    path = winreg.QueryValue(ip, "")
                                    exe  = Path(path.strip()) / "python.exe"
                                    if exe.exists():
                                        candidates.append((hive, str(exe)))
                                i += 1
                            except OSError:
                                break
                except OSError:
                    pass
    except ImportError:
        pass

    # PATH candidates
    for name in ["python3.11", "python3", "python"]:
        found = shutil.which(name)
        if found:
            candidates.append((None, found))

    candidates.append((None, sys.executable))

    for hive, exe in candidates:
        try:
            import winreg
            # Prefer user-level (HKCU) over system (HKLM) to avoid access issues
            if hive == winreg.HKEY_CURRENT_USER:
                return exe
        except Exception:
            pass

    # Fall back to anything that works
    for _, exe in candidates:
        try:
            out = subprocess.check_output(
                [exe, "-c", "import sys; v=sys.version_info; print(v.major,v.minor)"],
                timeout=5, capture_output=False,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            ).decode().strip()
            major, minor = map(int, out.split())
            if major == 3 and minor >= 11:
                return exe
        except Exception:
            continue

    return sys.executable


def _find_node() -> str | None:
    """Find node executable across common install paths."""
    node_paths = [
        shutil.which("node"),
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        str(Path.home() / "AppData" / "Roaming" / "nvm" / "current" / "node.exe"),
        str(INSTALL_ROOT / "node" / "node.exe"),
    ]
    for p in node_paths:
        if p and Path(p).exists():
            return p
    return None


def _find_npm() -> str | None:
    """Find npm executable across common install paths."""
    npm_paths = [
        shutil.which("npm"),
        r"C:\Program Files\nodejs\npm.cmd",
        r"C:\Program Files (x86)\nodejs\npm.cmd",
        str(Path.home() / "AppData" / "Roaming" / "nvm" / "current" / "npm.cmd"),
        str(INSTALL_ROOT / "node" / "npm.cmd"),
        str(Path.home() / "AppData" / "Roaming" / "npm" / "npm.cmd"),
    ]
    for p in npm_paths:
        if p and Path(p).exists():
            return p
    return None


def _download_node() -> bool:
    """Download Node.js v20 LTS portable into JARVIS/node/"""
    import zipfile
    node_dir = INSTALL_ROOT / "node"
    node_dir.mkdir(exist_ok=True)

    url     = "https://nodejs.org/dist/v20.18.0/node-v20.18.0-win-x64.zip"
    zip_path = node_dir / "node.zip"

    info("Downloading Node.js v20 LTS portable (~30MB) ...")
    try:
        def hook(b, bs, tot):
            pct = min(100, b * bs * 100 // (tot or 1))
            print(f"\r  [{pct:3d}%]", end="", flush=True)
        urllib.request.urlretrieve(url, str(zip_path), reporthook=hook)
        print()
    except Exception as e:
        err(f"Node.js download failed: {e}")
        return False

    info("Extracting Node.js ...")
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(str(node_dir / "tmp"))
        zip_path.unlink()

        # Move from nested subfolder up to node/
        for sub in (node_dir / "tmp").iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    dest = node_dir / f.name
                    if not dest.exists():
                        shutil.move(str(f), str(dest))
        shutil.rmtree(node_dir / "tmp", ignore_errors=True)
        ok("Node.js portable installed")
        return True
    except Exception as e:
        err(f"Node.js extract failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="JARVIS Installer")
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--skip-voice",  action="store_true")
    parser.add_argument("--skip-vscode", action="store_true")
    parser.add_argument("--no-launch",   action="store_true")
    args = parser.parse_args()

    print(f"\n{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     JARVIS Portable AI Workspace         ║")
    print("  ║     Installer v1.0                       ║")
    print("  ╚══════════════════════════════════════════╝")
    print(f"{RESET}")
    print(f"  Install root: {INSTALL_ROOT}")
    sep()

    steps = [
        ("System checks", check_system),
        ("Python venv",   setup_python_env),
        ("Ollama",        install_ollama),
        ("AI models",     lambda: pull_models(args.skip_models)),
        ("Voice tools",   lambda: install_voice(args.skip_voice)),
        ("Electron",      setup_electron),
        ("VS Code",       lambda: install_vscode(args.skip_vscode)),
        ("Config",        generate_config),
        ("Health check",  run_health_check),
    ]

    results = []
    for name, fn in steps:
        try:
            result = fn()
            results.append((name, result))
        except Exception as e:
            err(f"Unexpected error in {name}: {e}")
            results.append((name, False))

    h("Installation Summary")
    sep()
    all_passed = True
    for name, passed in results:
        mark = f"{GREEN}✓" if passed else f"{RED}✗"
        label = "OK" if passed else "FAILED"
        print(f"  {mark}  {name:<25} {label}{RESET}")
        if not passed:
            all_passed = False
    sep()

    if all_passed:
        print(f"\n  {GREEN}{BOLD}JARVIS is ready!{RESET}")
    else:
        print(f"\n  {YELLOW}Some steps failed — see above for details.{RESET}")

    launch_jarvis(args.no_launch)
    print()


if __name__ == "__main__":
    main()
