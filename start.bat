@echo off
title KALI
echo ========================================
echo   KALI - Kernel Agent Lifecycle Intelligence
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from python.org
    pause
    exit /b 1
)

:: Check if .venv exists
if not exist ".venv" (
    echo [SETUP] First run - installing dependencies...
    pip install uv >nul 2>&1
    uv sync --all-extras
    echo [SETUP] Dependencies installed!
    echo.
)

:: Check if .env exists
if not exist ".env" (
    echo [SETUP] Creating .env from template...
    copy .env.example .env >nul
    echo [SETUP] Edit .env to add your API keys
    echo.
)

:: Start RVC voice conversion (WSL, conda rvc, port 3003)
echo [START] Starting RVC JARVIS voice conversion (WSL, port 3003)...
start "" wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate rvc && python /mnt/c/Users/User/Desktop/Jarvis/services/rvc/server.py"
timeout /t 8 /nobreak >nul

:: Start TTS service (WSL, Silero + RVC, port 3002)
echo [START] Starting Silero TTS + RVC pipeline (WSL, port 3002)...
start "" wsl bash -c "cd ~/kali-tts-wsl && source .venv/bin/activate && python /mnt/c/Users/User/Desktop/Jarvis/services/tts/server.py"
timeout /t 15 /nobreak >nul

:: Start kernel (port 3005)
echo [START] Starting KALI kernel on port 3005...
start /b "" uv run uvicorn kernel.main:create_app --factory --host 0.0.0.0 --port 3005

:: Wait for kernel to start
timeout /t 3 /nobreak >nul

:: Check if UI needs install
if not exist "ui\node_modules" (
    echo [SETUP] Installing UI dependencies...
    cd ui && call pnpm install && cd ..
)

:: Start UI
echo [START] Starting UI on port 1420...
echo.
echo ========================================
echo   KALI is running!
echo   UI:      http://localhost:1420
echo   Kernel:  http://localhost:3005/health
echo   TTS:     http://localhost:3002/health
echo   RVC:     http://localhost:3003/health
echo   Press Ctrl+C to stop
echo ========================================
echo.

cd ui && call pnpm dev
