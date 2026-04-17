@echo off
title KALI
echo ========================================
echo   KALI - Kernel Agent Lifecycle Intelligence
echo ========================================
echo.

if "%KALI_HOST%"=="" set "KALI_HOST=127.0.0.1"
if "%KALI_PORT%"=="" set "KALI_PORT=3005"

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

:: Start kernel (native Windows, in-process TTS)
echo [START] Starting KALI kernel on %KALI_HOST%:%KALI_PORT%...
start /b "" uv run uvicorn kernel.main:create_app --factory --host %KALI_HOST% --port %KALI_PORT%

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
echo   Kernel:  http://%KALI_HOST%:%KALI_PORT%/health
echo   Voice:   in-process (kernel /tts, /tts/speak)
echo   Press Ctrl+C to stop
echo ========================================
echo.

cd ui && call pnpm dev
