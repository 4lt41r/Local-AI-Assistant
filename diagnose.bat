@echo off
echo ============================================
echo  JARVIS Diagnostics
echo ============================================
echo.

echo [1] Python location:
where python
python --version
echo.

echo [2] Venv attempt:
python -m venv C:\Users\%USERNAME%\AppData\Local\Temp\test_venv_jarvis 2>&1
echo Exit code: %errorlevel%
rmdir /s /q C:\Users\%USERNAME%\AppData\Local\Temp\test_venv_jarvis >nul 2>&1
echo.

echo [3] pip install test:
if exist "F:\JARVIS\venv\Scripts\pip.exe" (
  echo pip found at F:\JARVIS\venv\Scripts\pip.exe
  F:\JARVIS\venv\Scripts\pip.exe --version
) else (
  echo NO pip found in venv
)
echo.

echo [4] npm / node:
where node 2>&1
where npm 2>&1
node --version 2>&1
npm --version 2>&1
echo.

echo [5] Electron package.json:
if exist "F:\JARVIS\launcher\package.json" (
  echo package.json EXISTS
  type "F:\JARVIS\launcher\package.json"
) else (
  echo package.json MISSING
)
echo.

echo [6] npm install error:
cd /d "F:\JARVIS\launcher"
call npm install 2>&1
echo Exit: %errorlevel%
echo.

echo [7] requirements.txt:
if exist "F:\JARVIS\backend\requirements.txt" (
  echo requirements.txt EXISTS:
  type "F:\JARVIS\backend\requirements.txt"
) else (
  echo requirements.txt MISSING
)
echo.

echo [8] Voice folder:
if exist "F:\JARVIS\voice" (dir "F:\JARVIS\voice" /s /b) else (echo voice folder missing)
echo.

echo [9] Backend health:
curl -s http://localhost:8000/health 2>&1
echo.
curl -s http://localhost:11434/api/tags 2>&1
echo.
pause
