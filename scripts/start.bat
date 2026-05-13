@echo off
title JARVIS Portable AI Workspace
cd /d "%~dp0.."
setlocal EnableDelayedExpansion

echo.
echo  ============================================
echo   JARVIS Portable AI Workspace  v1.0
echo  ============================================
echo.

REM ── Core paths ───────────────────────────────────
set JARVIS_ROOT=%~dp0..
set OLLAMA_MODELS=%JARVIS_ROOT%\models\ollama
set OLLAMA_NUM_GPU=1
set OLLAMA_KEEP_ALIVE=5m
set PYTHONPATH=%JARVIS_ROOT%\backend
set STEP_FILE=%JARVIS_ROOT%\config\install_steps.txt

REM ── Add ALL known tool locations to PATH ─────────
REM    Ollama - system install locations
set PATH=%PATH%;C:\Users\%USERNAME%\AppData\Local\Programs\Ollama
set PATH=%PATH%;C:\Program Files\Ollama
REM    Ollama - portable (inside JARVIS)
set PATH=%PATH%;%JARVIS_ROOT%\ollama

REM    Node.js - common system install locations
set PATH=%PATH%;C:\Program Files\nodejs
set PATH=%PATH%;C:\Program Files (x86)\nodejs
set PATH=%PATH%;%APPDATA%\nvm\current
set PATH=%PATH%;C:\Users\%USERNAME%\AppData\Roaming\nvm\current
REM    Node.js - portable (inside JARVIS)
set PATH=%PATH%;%JARVIS_ROOT%\node\

REM    npm global (for electron)
set PATH=%PATH%;%APPDATA%\npm

REM ── Create required dirs ─────────────────────────
if not exist "%JARVIS_ROOT%\config"       mkdir "%JARVIS_ROOT%\config"
if not exist "%JARVIS_ROOT%\models\ollama" mkdir "%JARVIS_ROOT%\models\ollama"
if not exist "%JARVIS_ROOT%\logs"         mkdir "%JARVIS_ROOT%\logs"

echo  Checking installation status...
echo  ════════════════════════════════════════════
echo.

REM ══════════════════════════════════════════════════
REM  STEP 1 — Python venv
REM ══════════════════════════════════════════════════
set STEP=python_venv
call :CHECK_STEP %STEP%
if "!STEP_DONE!"=="1" (
  echo  [SKIP] Python venv already set up
  goto :step2
)

echo  [....] Checking Python venv...
if exist "%JARVIS_ROOT%\venv\Scripts\python.exe" (
  echo  [OK]   Python venv found
  call :MARK_STEP %STEP%
  goto :step2
)

python --version >nul 2>&1
if errorlevel 1 (
  echo  [FAIL] Python not found.
  echo         Install Python 3.11+ from https://python.org
  echo         Make sure to check "Add Python to PATH" during install.
  pause & exit /b 1
)

echo  [....] Creating Python venv...
python -m venv "%JARVIS_ROOT%\venv"
if errorlevel 1 (
  echo  [....] Retrying with --without-pip flag (avoids Access Denied errors)...
  python -m venv --without-pip "%JARVIS_ROOT%\venv"
  if errorlevel 1 (
    echo  [FAIL] Could not create venv.
    echo         Try running this bat as Administrator once to create the venv.
    pause & exit /b 1
  )
  REM Bootstrap pip into the venv
  "%JARVIS_ROOT%\venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1
)

echo  [....] Installing Python dependencies...
"%JARVIS_ROOT%\venv\Scripts\pip.exe" install --quiet --upgrade pip
"%JARVIS_ROOT%\venv\Scripts\pip.exe" install --quiet -r "%JARVIS_ROOT%\backend\requirements.txt"
if errorlevel 1 (
  echo  [WARN] Some pip packages failed - will retry on next launch
) else (
  echo  [OK]   Python venv ready
  call :MARK_STEP %STEP%
)

:step2
REM ══════════════════════════════════════════════════
REM  STEP 2 — Node.js
REM ══════════════════════════════════════════════════
set STEP=nodejs
call :CHECK_STEP %STEP%
if "!STEP_DONE!"=="1" (
  echo  [SKIP] Node.js already set up
  goto :step3
)

echo  [....] Checking Node.js...
node --version >nul 2>&1
if not errorlevel 1 (
  for /f "tokens=*" %%v in ('node --version 2^>nul') do set NODE_VER=%%v
  echo  [OK]   Node.js !NODE_VER! found
  call :MARK_STEP %STEP%
  goto :step3
)

REM Not found anywhere - download portable Node.js into JARVIS\node\
echo  [....] Node.js not found. Downloading portable Node.js to %JARVIS_ROOT%\node\
if not exist "%JARVIS_ROOT%\node" mkdir "%JARVIS_ROOT%\node"

REM Get latest LTS zip (node 20 LTS)
set NODE_URL=https://nodejs.org/dist/v20.18.0/node-v20.18.0-win-x64.zip
set NODE_ZIP=%JARVIS_ROOT%\node\node.zip

echo  [....] Downloading Node.js v20 LTS (~30MB)...
curl -L "%NODE_URL%" -o "%NODE_ZIP%" --progress-bar
if errorlevel 1 (
  echo  [FAIL] Node.js download failed. Check internet connection.
  echo         Or install manually from https://nodejs.org (LTS)
  pause & exit /b 1
)

echo  [....] Extracting Node.js...
powershell -Command "Expand-Archive -Path '%NODE_ZIP%' -DestinationPath '%JARVIS_ROOT%\node\tmp' -Force"
REM Move contents up one level (zip has a subfolder)
for /d %%d in ("%JARVIS_ROOT%\node\tmp\node-*") do (
  xcopy "%%d\*" "%JARVIS_ROOT%\node\" /E /I /Q >nul
)
rmdir /s /q "%JARVIS_ROOT%\node\tmp" >nul 2>&1
del "%NODE_ZIP%" >nul 2>&1

REM Verify
node --version >nul 2>&1
if errorlevel 1 (
  echo  [FAIL] Node.js still not found after extraction
  pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>nul') do set NODE_VER=%%v
echo  [OK]   Node.js !NODE_VER! portable ready
call :MARK_STEP %STEP%

:step3
REM ══════════════════════════════════════════════════
REM  STEP 3 — Ollama
REM ══════════════════════════════════════════════════
set STEP=ollama
call :CHECK_STEP %STEP%
if "!STEP_DONE!"=="1" (
  echo  [SKIP] Ollama already installed
  goto :step3b
)

echo  [....] Checking Ollama...
where ollama >nul 2>&1
if not errorlevel 1 (
  echo  [OK]   Ollama found in PATH
  call :MARK_STEP %STEP%
  goto :step3b
)

REM Download portable Ollama zip into JARVIS\ollama\
echo  [....] Ollama not found. Downloading portable version to %JARVIS_ROOT%\ollama\
if not exist "%JARVIS_ROOT%\ollama" mkdir "%JARVIS_ROOT%\ollama"

echo  [....] Downloading Ollama portable (~50MB)...
curl -L "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip" -o "%JARVIS_ROOT%\ollama\ollama.zip" --progress-bar
if errorlevel 1 (
  echo  [FAIL] Ollama download failed. Check internet connection.
  echo         Or install manually from https://ollama.com/download
  pause & exit /b 1
)

echo  [....] Extracting Ollama...
powershell -Command "Expand-Archive -Path '%JARVIS_ROOT%\ollama\ollama.zip' -DestinationPath '%JARVIS_ROOT%\ollama' -Force"
del "%JARVIS_ROOT%\ollama\ollama.zip" >nul 2>&1

where ollama >nul 2>&1
if errorlevel 1 (
  echo  [FAIL] Ollama still not found after extraction
  pause & exit /b 1
)
echo  [OK]   Ollama portable ready
call :MARK_STEP %STEP%

:step3b
REM ── Start Ollama service if not running ──────────
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo  [....] Starting Ollama service...
  start /B "" ollama serve >"%JARVIS_ROOT%\logs\ollama.log" 2>&1
  timeout /t 5 /nobreak >nul
  curl -s http://localhost:11434/api/tags >nul 2>&1
  if errorlevel 1 (
    echo  [WARN] Ollama slow to start - will retry at runtime
  ) else (
    echo  [OK]   Ollama service running on :11434
  )
) else (
  echo  [OK]   Ollama service already running
)

REM ══════════════════════════════════════════════════
REM  STEP 4 — AI Models
REM ══════════════════════════════════════════════════
set STEP=models
call :CHECK_STEP %STEP%
if "!STEP_DONE!"=="1" (
  echo  [SKIP] Models already pulled
  goto :step5
)

echo  [....] Checking AI models...
ollama list 2>nul | findstr /i "llama3" >nul 2>&1
if not errorlevel 1 (
  echo  [OK]   Models already present
  call :MARK_STEP %STEP%
  goto :step5
)

echo.
echo  [INFO] No models found.
echo         Pulling downloads ~15GB total across 3-4 models.
echo         You can skip now and pull later manually.
echo.
set /p PULL_NOW="  Pull models now? [Y/n]: "
if /i "!PULL_NOW!"=="n" (
  echo  [SKIP] Run later:  ollama pull llama3.1:8b
  goto :step5
)

echo.
echo  [....] Pulling llama3.1:8b  (general - ~4.7GB)...
ollama pull llama3.1:8b
echo  [....] Pulling qwen2.5-coder:7b  (code - ~4.4GB)...
ollama pull qwen2.5-coder:7b
echo  [....] Pulling deepseek-r1:7b  (reasoning - ~4.4GB)...
ollama pull deepseek-r1:7b
echo.
set /p PULL_VISION="  Pull llava:7b vision model too? (~4.7GB) [y/N]: "
if /i "!PULL_VISION!"=="y" (
  echo  [....] Pulling llava:7b  (vision)...
  ollama pull llava:7b
)

echo  [OK]   Models ready
call :MARK_STEP %STEP%

:step5
REM ══════════════════════════════════════════════════
REM  STEP 5 — Electron node_modules
REM ══════════════════════════════════════════════════
set STEP=node_modules
call :CHECK_STEP %STEP%
if "!STEP_DONE!"=="1" (
  echo  [SKIP] Electron modules already installed
  goto :step6
)

echo  [....] Checking Electron dependencies...
if exist "%JARVIS_ROOT%\launcher\node_modules\electron" (
  echo  [OK]   Electron modules found
  call :MARK_STEP %STEP%
  goto :step6
)

echo  [....] Running npm install (first time only)...
cd "%JARVIS_ROOT%\launcher"
call npm install --prefer-offline
if errorlevel 1 (
  echo  [FAIL] npm install failed
  cd "%JARVIS_ROOT%"
  pause & exit /b 1
)
cd "%JARVIS_ROOT%"
echo  [OK]   Electron ready
call :MARK_STEP %STEP%

:step6
REM ══════════════════════════════════════════════════
REM  STEP 6 — jarvis.json config
REM ══════════════════════════════════════════════════
set STEP=config
call :CHECK_STEP %STEP%
if "!STEP_DONE!"=="1" (
  echo  [SKIP] Config already created
  goto :launch
)

if exist "%JARVIS_ROOT%\config\jarvis.json" (
  echo  [OK]   jarvis.json found
  call :MARK_STEP %STEP%
  goto :launch
)

echo  [....] Creating jarvis.json...
set JR=%JARVIS_ROOT:\=\\%
(
echo {
echo   "version": "1.0.0",
echo   "install_root": "%JR%",
echo   "backend_port": 8000,
echo   "ollama_host": "http://localhost:11434",
echo   "ollama_keep_alive": "5m",
echo   "default_model": "llama3.1:8b",
echo   "models": {
echo     "code":      "qwen2.5-coder:7b",
echo     "reasoning": "deepseek-r1:7b",
echo     "general":   "llama3.1:8b",
echo     "vision":    "llava:7b"
echo   },
echo   "voice": {
echo     "wake_word": "hey jarvis",
echo     "whisper_model": "base.en",
echo     "piper_voice": "en_US-lessac-medium",
echo     "enabled": true
echo   },
echo   "gpu": {
echo     "num_gpu": 1,
echo     "vram_limit_gb": 4.0
echo   }
echo }
) > "%JARVIS_ROOT%\config\jarvis.json"
echo  [OK]   jarvis.json created
call :MARK_STEP %STEP%

:launch
REM ══════════════════════════════════════════════════
REM  LAUNCH JARVIS
REM ══════════════════════════════════════════════════
echo.
echo  ════════════════════════════════════════════
echo   All checks passed. Launching JARVIS...
echo  ════════════════════════════════════════════
echo.
cd "%JARVIS_ROOT%\launcher"
call npm start
pause
goto :EOF

REM ══════════════════════════════════════════════════
REM  HELPERS
REM ══════════════════════════════════════════════════
:CHECK_STEP
set STEP_DONE=0
if not exist "%STEP_FILE%" goto :EOF
findstr /i "^%~1$" "%STEP_FILE%" >nul 2>&1
if not errorlevel 1 set STEP_DONE=1
goto :EOF

:MARK_STEP
echo %~1>> "%STEP_FILE%"
goto :EOF
