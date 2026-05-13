"""
installer/select_drive.py — Interactive install drive selector
Detects removable + fixed drives, lets user choose, copies JARVIS.
Run this BEFORE install.py when deploying to external SSD.

Usage:
  python installer/select_drive.py
  python installer/select_drive.py --drive E:
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
INSTALL_ROOT = SCRIPT_DIR.parent

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# Folders to exclude from copy (large / re-installable)
EXCLUDE = {
    "venv", "node_modules", "__pycache__", ".git",
    "dist", "models",   # models re-pulled on destination
}


def list_drives() -> list[dict]:
    """List all drives with free space info (Windows)."""
    drives = []
    try:
        output = subprocess.check_output(
            ["wmic", "logicaldisk", "get",
             "DeviceID,DriveType,FreeSpace,Size,VolumeName",
             "/format:csv"],
            text=True, timeout=10
        )
        for line in output.strip().splitlines()[2:]:
            parts = line.strip().split(",")
            if len(parts) < 6:
                continue
            _, device, dtype, free, size, label = parts[:6]
            try:
                free_gb = int(free) / 1e9 if free else 0
                size_gb = int(size) / 1e9 if size else 0
                dtype   = int(dtype) if dtype else 0
                drives.append({
                    "device":  device.strip(),
                    "label":   label.strip() or "Local Disk",
                    "type":    "Removable" if dtype == 2 else "Fixed" if dtype == 3 else "Other",
                    "free_gb": round(free_gb, 1),
                    "size_gb": round(size_gb, 1),
                })
            except Exception:
                pass
    except Exception:
        pass
    return [d for d in drives if d["free_gb"] > 0]


def display_drives(drives: list[dict]):
    print(f"\n  {'#':<4} {'DRIVE':<8} {'TYPE':<12} {'FREE':<10} {'SIZE':<10} {'LABEL'}")
    print("  " + "─" * 58)
    for i, d in enumerate(drives, 1):
        removable = f"{CYAN}← SSD{RESET}" if d["type"] == "Removable" else ""
        free_col  = f"{GREEN}{d['free_gb']} GB{RESET}" if d["free_gb"] > 15 else f"{YELLOW}{d['free_gb']} GB{RESET}"
        print(
            f"  {i:<4} {d['device']:<8} {d['type']:<12} "
            f"{free_col:<20} {d['size_gb']:<10} {d['label']} {removable}"
        )


def estimate_size() -> float:
    """Estimate copy size in GB (excludes excluded dirs)."""
    total = 0
    for item in INSTALL_ROOT.rglob("*"):
        if any(ex in item.parts for ex in EXCLUDE):
            continue
        if item.is_file():
            try:
                total += item.stat().st_size
            except Exception:
                pass
    return total / 1e9


def copy_jarvis(dest_drive: str) -> bool:
    """Copy JARVIS to destination drive."""
    dest = Path(dest_drive) / "JARVIS"
    print(f"\n  {YELLOW}Copying JARVIS → {dest}{RESET}")

    est = estimate_size()
    print(f"  Estimated size: ~{est:.1f} GB (excluding models)")

    if dest.exists():
        resp = input(f"\n  {YELLOW}Destination exists. Overwrite? [y/N]: {RESET}").strip().lower()
        if resp != "y":
            print("  Cancelled.")
            return False
        shutil.rmtree(dest)

    def ignore_fn(src, names):
        return [n for n in names if n in EXCLUDE]

    try:
        print("  Copying files...", end="", flush=True)
        shutil.copytree(str(INSTALL_ROOT), str(dest), ignore=ignore_fn)
        print(f"\r  {GREEN}✓ Copied to {dest}{RESET}           ")
    except Exception as e:
        print(f"\n  {RED}✗ Copy failed: {e}{RESET}")
        return False

    # Write portable marker so JARVIS knows its root
    marker = dest / "config" / ".portable"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(str(dest), encoding="utf-8")

    # Create launch shortcut on drive root
    bat = Path(dest_drive) / "Launch JARVIS.bat"
    bat.write_text(
        f'@echo off\ncd /d "{dest}\\launcher"\ncall npm start\n',
        encoding="utf-8"
    )
    print(f"  {GREEN}✓ Launch shortcut: {bat}{RESET}")

    print(f"\n  {GREEN}{BOLD}JARVIS deployed to {dest}{RESET}")
    print(f"  Next: run  {dest}\\installer\\install.py  on the target machine")
    return True


def main():
    parser = argparse.ArgumentParser(description="JARVIS Drive Selector")
    parser.add_argument("--drive", help="Target drive letter (e.g. E:)")
    parser.add_argument("--list",  action="store_true", help="List drives and exit")
    args = parser.parse_args()

    print(f"\n{BOLD}{CYAN}  JARVIS — Portable Drive Selector{RESET}")

    drives = list_drives()
    display_drives(drives)

    if args.list:
        return

    if args.drive:
        chosen = args.drive.rstrip("\\").rstrip("/")
    else:
        print()
        try:
            choice = input("  Select drive number (or enter drive letter): ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(drives):
                    chosen = drives[idx]["device"]
                else:
                    print(f"  {RED}Invalid selection{RESET}")
                    sys.exit(1)
            else:
                chosen = choice.rstrip("\\")
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            sys.exit(0)

    copy_jarvis(chosen)


if __name__ == "__main__":
    main()
