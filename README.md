# JARVIS Portable AI Workspace

A fully local, portable AI workstation. No cloud dependency. Runs from external SSD.

---

## Quick Start

### Option A — Fresh Install

```bat
python installer\install.py
```

This runs all 10 steps automatically. Takes 10–30 minutes depending on internet speed (model downloads).

### Option B — Step by step

```bat
python installer\setup_env.py          # Set environment variables
python installer\install_ollama.py     # Install + start Ollama
python installer\install_models.py     # Pull AI models (~15GB total)
python installer\install_voice.py      # Download Whisper + Piper
python installer\install_vscode.py     # VS Code portable (optional)
cd launcher && npm install             # Electron dependencies
scripts\start.bat                      # Launch JARVIS
```

### Option C — Deploy to External SSD

```bat
python installer\select_drive.py       # Choose target drive
# Then on the target machine:
python installer\install.py --skip-models   # (pull models separately)
python installer\install_models.py
```

---

## CLI Flags

| Flag | Effect |
|---|---|
| `--skip-models` | Skip model downloads (pull later) |
| `--skip-voice`  | Skip Whisper + Piper install |
| `--skip-vscode` | Skip VS Code install |
| `--no-launch`   | Don't open JARVIS after install |

---

## Project Structure

```
JARVIS/
├── installer/        Setup automation
├── launcher/         Electron app (frontend)
├── backend/          FastAPI backend
├── voice/            Whisper + Piper binaries
├── models/           Routing config
├── vscode/           VS Code portable
├── scripts/          Launchers + utilities
├── config/           jarvis.json + recents
├── logs/             Runtime logs
└── JARVIS.code-workspace
```

---

## AI Models

| Model | Role | VRAM |
|---|---|---|
| `llama3.1:8b` | General assistant | ~4 GB |
| `qwen2.5-coder:7b` | Code generation | ~3.8 GB |
| `deepseek-r1:7b` | Reasoning & planning | ~3.8 GB |
| `llava:7b` | Vision (on-demand) | ~4 GB |

One model loaded at a time. Auto-unloads after 5 min idle.

---

## Backend API

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `POST /chat` | AI chat |
| `WS /ws` | Streaming chat |
| `GET /models` | Model status |
| `POST /models/switch` | Switch active model |
| `POST /routing/classify` | Test task classifier |
| `POST /voice/start` | Begin STT capture |
| `POST /voice/speak` | TTS playback |
| `WS /voice/ws` | Full voice pipeline |
| `GET /system/stats` | RAM / VRAM / CPU |
| `POST /vscode/open` | Launch VS Code |
| `POST /vscode/assist` | Code AI assist |

Full docs: `http://localhost:8000/docs` (when backend is running)

---

## System Requirements

| Component | Minimum |
|---|---|
| OS | Windows 10/11 x64 |
| RAM | 16 GB |
| VRAM | 4 GB (NVIDIA) |
| Storage | 30 GB free on install drive |
| Python | 3.11+ |
| Node.js | 18+ |

---

## Voice Setup

After install:
1. Wake word: say **"Hey Jarvis"** (configurable in Settings)
2. Click the orb on the Voice page to start manual capture
3. Requires microphone access in Windows privacy settings

---

## VS Code + Continue.dev

1. Open VS Code: click **⟨/⟩ OPEN VS CODE** in the Code page
2. Install extension: `Continue.continue`
3. Copy `vscode/continue-config.json` → `~/.continue/config.json`
4. All 3 JARVIS models available in Continue sidebar

---

## Project Status

This repository contains a working local AI workspace prototype with an Electron frontend, FastAPI backend, Ollama model orchestration, and voice integration.

Current status:
- Installer scripts and setup flow are present
- Backend API and routing engine are implemented
- Voice capture and text-to-speech integration are included
- VS Code portable integration is scaffolded

Limitations:
- Development cannot continue further at this time due to budget, time, and hardware constraints
- The system has not been fully hardened for production use
- Additional testing, model packaging, and GUI polish remain incomplete
- GitHub push capability is not available from this local workspace because it is not initialized as a git repository

For details, see `LIMITATIONS.md`.

---

## Troubleshooting

**Backend offline**: Run `python scripts/health_check.py`

**Ollama not starting**: Check `logs/` folder, or run `ollama serve` manually

**Model download slow**: Use `python installer/install_models.py --skip-vision` to skip llava

**No GPU detected**: Runs in CPU mode (slower). Set `OLLAMA_NUM_GPU=0` in `setenv.bat`
