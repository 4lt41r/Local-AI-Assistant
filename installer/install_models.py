"""
installer/install_models.py — Pull all JARVIS AI models via Ollama
Fixed: encoding error on Windows (charmap codec)
"""

import subprocess
import sys
import time

MODELS = [
    ("llama3.1:8b",      "General purpose — ~4GB VRAM"),
    ("qwen2.5-coder:7b", "Code assistant — ~3.8GB VRAM"),
    ("deepseek-r1:7b",   "Reasoning/planning — ~3.8GB VRAM"),
    ("llava:7b",         "Vision (on-demand) — ~4GB VRAM"),
]

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"


def pull_model(name: str, description: str) -> bool:
    print(f"\n  {CYAN}Pulling {name}{RESET}")
    print(f"  {description}")
    print(f"  {'─' * 40}")

    try:
        proc = subprocess.Popen(
            ["ollama", "pull", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # FIX: force UTF-8 encoding — prevents charmap codec error on Windows
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                # Strip ANSI escape codes for clean display
                import re
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                print(f"  {clean}")
        proc.wait()
        if proc.returncode == 0:
            print(f"  {GREEN}✓ {name} ready{RESET}")
            return True
        else:
            print(f"  {RED}✗ Pull failed (exit {proc.returncode}){RESET}")
            return False
    except FileNotFoundError:
        print(f"  {RED}✗ 'ollama' not found in PATH{RESET}")
        return False
    except Exception as e:
        print(f"  {RED}✗ Error: {e}{RESET}")
        return False


def main():
    # FIX: set stdout to UTF-8 so Python itself doesn't crash on progress chars
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print(f"\n{YELLOW}  JARVIS Model Installer{RESET}")
    print(f"  Pulling sequentially to avoid OOM\n")

    skip_vision = "--skip-vision" in sys.argv
    results = []

    for name, desc in MODELS:
        if skip_vision and name == "llava:7b":
            print(f"\n  {YELLOW}Skipping {name} (--skip-vision){RESET}")
            continue
        ok = pull_model(name, desc)
        results.append((name, ok))
        if ok:
            time.sleep(1)

    print(f"\n  {'─' * 44}")
    for name, ok in results:
        mark = f"{GREEN}✓" if ok else f"{RED}✗"
        print(f"    {mark}  {name}{RESET}")
    print()


if __name__ == "__main__":
    main()
