"""
scripts/start_backend.py — Launches the FastAPI backend
Called by Electron main.js on app startup
"""

import os
import sys
from pathlib import Path

# Resolve paths
SCRIPT_DIR   = Path(__file__).resolve().parent
INSTALL_ROOT = SCRIPT_DIR.parent
BACKEND_DIR  = INSTALL_ROOT / "backend"
VENV_PYTHON  = INSTALL_ROOT / "venv" / "Scripts" / "python.exe"

# Add backend to path
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("JARVIS_ROOT", str(INSTALL_ROOT))

# Use venv python if available
if VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
    import subprocess
    result = subprocess.run(
        [str(VENV_PYTHON), __file__],
        env={**os.environ, "JARVIS_ROOT": str(INSTALL_ROOT)},
    )
    sys.exit(result.returncode)

# Launch uvicorn
import uvicorn

if __name__ == "__main__":
    from config import settings
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=settings.backend_port,
        app_dir=str(BACKEND_DIR),
        log_level="info",
        reload=False,
    )
