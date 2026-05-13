# JARVIS Portable AI Workspace — Architecture

## System Overview

A fully local, portable AI workstation running on external SSD.
No cloud dependency. All compute stays on-device.

---

## Communication Flow

```
User Input (Voice/Text/UI)
        │
        ▼
  Electron Frontend  ◄──────────────────────┐
  (Port 3000 local)                          │
        │  HTTP/WebSocket                    │ Events/Updates
        ▼                                    │
  FastAPI Backend (Port 8000)               │
        │                                    │
   ┌────┴─────────────────┐                 │
   │   AI Router Engine   │                 │
   └────┬─────────────────┘                 │
        │                                    │
   ┌────▼──────────────────────────────┐    │
   │         Ollama (Port 11434)       │    │
   │  qwen2.5-coder:7b  │ llama3.1:8b │    │
   │  deepseek-r1:7b    │ llava:7b     │    │
   └───────────────────────────────────┘    │
        │                                    │
   ┌────▼──────────────────────────────┐    │
   │     Voice Pipeline                │────┘
   │  Whisper.cpp (STT) │ Piper (TTS) │
   └───────────────────────────────────┘
```

---

## Folder Structure

```
JARVIS/
├── launcher/                    # Electron app
│   ├── main.js                  # Electron main process
│   ├── preload.js               # Context bridge
│   ├── package.json
│   └── renderer/                # UI layer
│       ├── index.html           # Entry point
│       ├── pages/
│       │   ├── home.html        # Molecular animation homepage
│       │   ├── chat.html        # AI chat interface
│       │   ├── code.html        # Coding assistant
│       │   ├── voice.html       # Voice assistant panel
│       │   └── settings.html    # Settings panel
│       ├── js/
│       │   ├── router.js        # SPA routing
│       │   ├── api.js           # Backend API client
│       │   ├── animation.js     # Three.js molecular system
│       │   └── voice-ui.js      # Voice UI controller
│       └── css/
│           └── tailwind.css
│
├── backend/                     # FastAPI backend
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Central config
│   ├── routers/
│   │   ├── chat.py              # Chat endpoints
│   │   ├── models.py            # Model management
│   │   ├── voice.py             # Voice endpoints
│   │   ├── system.py            # System monitoring
│   │   └── vscode.py            # VS Code integration
│   ├── services/
│   │   ├── ollama_manager.py    # Ollama lifecycle
│   │   ├── router_engine.py     # AI task router
│   │   ├── task_classifier.py   # Prompt classifier
│   │   ├── voice_stt.py         # Whisper STT
│   │   ├── voice_tts.py         # Piper TTS
│   │   └── system_monitor.py   # RAM/GPU monitor
│   └── requirements.txt
│
├── models/                      # Model config (Ollama managed)
│   └── routing_config.json      # Model routing rules
│
├── voice/                       # Voice binaries
│   ├── whisper/                 # whisper.cpp binary + model
│   └── piper/                   # piper binary + voice model
│
├── vscode/                      # VS Code portable
│   └── data/                    # VS Code user data (portable mode)
│
├── installer/                   # Setup automation
│   ├── install.py               # Master installer
│   ├── install_ollama.py        # Ollama installer
│   ├── install_models.py        # Model puller
│   ├── install_voice.py         # Voice tools installer
│   └── install_vscode.py        # VS Code portable installer
│
├── scripts/                     # Utility scripts
│   ├── start.bat                # Windows launcher
│   ├── start_backend.py         # Backend launcher
│   └── health_check.py         # Service health check
│
├── logs/                        # Runtime logs
├── config/
│   └── jarvis.json              # Global config
└── README.md
```

---

## Module Breakdown

| Module | Tech | Role |
|--------|------|------|
| Electron Launcher | Electron + HTML/Tailwind | UI shell, SPA routing |
| Molecular Homepage | Three.js + WebGL | Animated entry screen |
| FastAPI Backend | Python + FastAPI | API gateway, orchestration |
| Ollama Manager | Python + httpx | Model lifecycle control |
| AI Router | Python | Task classification + model dispatch |
| Voice STT | Whisper.cpp | Speech → Text |
| Voice TTS | Piper | Text → Speech |
| VS Code Integration | Shell + Continue.dev | Coding workspace |
| Installer | Python scripts | Automated setup |

---

## Dependency Map

```
Electron
  └── Node.js ≥ 18
  └── Tailwind (CDN or compiled)
  └── Three.js (CDN)

FastAPI Backend
  └── Python 3.11+
  └── fastapi
  └── uvicorn
  └── httpx (Ollama API calls)
  └── websockets
  └── psutil (system monitor)
  └── pyaudio (mic input)

Ollama
  └── ollama.exe (Windows)
  └── Models: qwen2.5-coder:7b, deepseek-r1:7b, llama3.1:8b, llava:7b

Voice
  └── whisper.cpp (prebuilt binary)
  └── whisper model: ggml-base.en.bin (~150MB)
  └── piper (prebuilt binary)
  └── piper voice: en_US-lessac-medium (~60MB)
```

---

## Installation Flow

```
install.py
  1. Check Python, Node.js versions
  2. Install Ollama → start service
  3. Pull AI models (sequential to avoid OOM)
  4. Download Whisper.cpp binary + model
  5. Download Piper binary + voice
  6. Install Python dependencies (venv)
  7. Install Node dependencies (npm install)
  8. Download VS Code portable (optional)
  9. Generate jarvis.json config
  10. Run health_check.py
  11. Launch JARVIS
```

---

## Lightweight Optimization Strategy

### RAM (target: stay under 12GB active)
- Only ONE Ollama model loaded at a time
- Auto-unload after 5min idle (Ollama `OLLAMA_KEEP_ALIVE=5m`)
- FastAPI runs async — no thread blocking
- Electron: disable GPU sandbox for lightweight mode

### VRAM (RTX 3050 4GB)
- 7B models: ~4GB VRAM with Q4 quantization (fits exactly)
- Set `OLLAMA_NUM_GPU=1` for GPU offload
- llava:7b vision only loaded on-demand

### Storage (External SSD)
- All paths relative to install root
- Ollama models stored on SSD (`OLLAMA_MODELS` env var)
- VS Code portable mode (no system install)

### Startup Speed
- Backend starts async with lazy service init
- Models NOT preloaded — loaded on first request
- Electron loads minimal shell first, then lazy-loads pages

---

## Key Config: `config/jarvis.json`

```json
{
  "version": "1.0.0",
  "install_root": "auto-detected",
  "backend_port": 8000,
  "electron_port": 3000,
  "ollama_host": "http://localhost:11434",
  "ollama_keep_alive": "5m",
  "default_model": "llama3.1:8b",
  "models": {
    "code": "qwen2.5-coder:7b",
    "reasoning": "deepseek-r1:7b",
    "general": "llama3.1:8b",
    "vision": "llava:7b"
  },
  "voice": {
    "wake_word": "hey jarvis",
    "whisper_model": "base.en",
    "piper_voice": "en_US-lessac-medium"
  },
  "gpu": {
    "num_gpu": 1,
    "vram_limit_gb": 4
  }
}
```
