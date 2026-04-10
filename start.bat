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

:: Start TTS service (Qwen3-TTS JARVIS voice on GPU)
echo [START] Starting JARVIS voice TTS on GPU (port 3001)...
start /b "" C:\Users\User\miniforge3\condabin\conda.bat run -n kali-tts --no-banner python services\tts\server.py
timeout /t 10 /nobreak >nul

:: Start kernel
echo [START] Starting KALI kernel on port 3000...
start /b "" uv run uvicorn kernel.main:create_app --factory --port 3000

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
echo   UI:    http://localhost:1420
echo   API:   http://localhost:3000/health
echo   TTS:   http://localhost:3001/health
echo   Press Ctrl+C to stop
echo ========================================
echo.

cd ui && call pnpm dev
