"""
installer/setup_env.py — Configure Windows environment variables for JARVIS
Sets JARVIS_ROOT, OLLAMA_MODELS, OLLAMA_NUM_GPU, OLLAMA_KEEP_ALIVE
Writes a setenv.bat for portable use without system-wide changes.
"""

import os
import sys
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR  = INSTALL_ROOT / "scripts"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"


def write_setenv_bat():
    """Write scripts/setenv.bat — source before running backend manually."""
    content = f"""@echo off
REM JARVIS Environment Variables
set JARVIS_ROOT={INSTALL_ROOT}
set OLLAMA_MODELS={INSTALL_ROOT}\\models\\ollama
set OLLAMA_NUM_GPU=1
set OLLAMA_KEEP_ALIVE=5m
set PYTHONPATH={INSTALL_ROOT}\\backend
set PATH={INSTALL_ROOT}\\venv\\Scripts;{INSTALL_ROOT}\\ollama;%PATH%
echo JARVIS environment loaded.
"""
    SCRIPTS_DIR.mkdir(exist_ok=True)
    bat = SCRIPTS_DIR / "setenv.bat"
    bat.write_text(content, encoding="utf-8")
    print(f"  {GREEN}✓ setenv.bat written → {bat}{RESET}")
    return bat


def write_activate_ps1():
    """PowerShell equivalent for those who prefer it."""
    content = f"""# JARVIS PowerShell Environment
$env:JARVIS_ROOT = "{INSTALL_ROOT}"
$env:OLLAMA_MODELS = "{INSTALL_ROOT}\\models\\ollama"
$env:OLLAMA_NUM_GPU = "1"
$env:OLLAMA_KEEP_ALIVE = "5m"
$env:PYTHONPATH = "{INSTALL_ROOT}\\backend"
$env:PATH = "{INSTALL_ROOT}\\venv\\Scripts;{INSTALL_ROOT}\\ollama;" + $env:PATH
Write-Host "JARVIS environment loaded." -ForegroundColor Cyan
"""
    ps1 = SCRIPTS_DIR / "setenv.ps1"
    ps1.write_text(content, encoding="utf-8")
    print(f"  {GREEN}✓ setenv.ps1 written → {ps1}{RESET}")


def set_user_env_vars():
    """Set persistent user-level environment variables (Windows registry)."""
    if sys.platform != "win32":
        print(f"  {YELLOW}Windows only — skipping registry env vars{RESET}")
        return

    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0, winreg.KEY_SET_VALUE
        )
        vars_to_set = {
            "JARVIS_ROOT":      str(INSTALL_ROOT),
            "OLLAMA_MODELS":    str(INSTALL_ROOT / "models" / "ollama"),
            "OLLAMA_NUM_GPU":   "1",
            "OLLAMA_KEEP_ALIVE": "5m",
        }
        for name, value in vars_to_set.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
        winreg.CloseKey(key)

        # Broadcast WM_SETTINGCHANGE so new terminals pick up the vars
        import ctypes
        HWND_BROADCAST   = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment")

        print(f"  {GREEN}✓ User environment variables set{RESET}")
    except Exception as e:
        print(f"  {YELLOW}Could not set registry env vars: {e}{RESET}")
        print(f"  Use setenv.bat / setenv.ps1 instead")


def main():
    print(f"\n{YELLOW}  JARVIS Environment Setup{RESET}\n")
    write_setenv_bat()
    write_activate_ps1()
    set_user_env_vars()

    print(f"\n  {YELLOW}Usage:{RESET}")
    print(f"    CMD:        scripts\\setenv.bat")
    print(f"    PowerShell: . scripts\\setenv.ps1\n")


if __name__ == "__main__":
    main()
