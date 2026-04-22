@echo off
REM Build Premium installer via InnoSetup (replaces 7z SFX — no 4GB limit).
REM Prereq: premium_stage\ already built (scripts\build_backend_premium.py + staging).
REM Install InnoSetup: winget install -e --id JRSoftware.InnoSetup

setlocal
cd /d "%~dp0\.."

set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\iscc.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\iscc.exe"
if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\iscc.exe"
if exist "C:\Program Files\Inno Setup 6\iscc.exe" set "ISCC=C:\Program Files\Inno Setup 6\iscc.exe"

if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 not found.
    echo Install it: winget install -e --id JRSoftware.InnoSetup
    exit /b 1
)

if not exist "dist_premium\premium_stage\kali-backend\kali-backend.exe" (
    echo ERROR: premium_stage not built yet.
    echo Run first: uv run --with pyinstaller python scripts\build_backend_premium.py
    echo Then stage: xcopy /E /I /Y dist_premium\kali-backend dist_premium\premium_stage\kali-backend
    exit /b 1
)

echo ============================================
echo   Building KALI Premium installer via InnoSetup
echo ============================================
echo Source:  dist_premium\premium_stage\
echo Output:  dist_premium\KALI-Premium-Setup-0.2.0-beta.exe
echo Compression: lzma2/ultra64 (slow but small)
echo.
echo This takes ~15-30 minutes for ~9 GB content. Be patient.
echo.

"%ISCC%" scripts\installer_premium.iss

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build FAILED with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)

echo.
echo ============================================
echo   Build complete!
echo ============================================
dir dist_premium\KALI-Premium-Setup-0.2.0-beta.exe
echo.
echo Share this file with friends via Google Drive / Yandex.Disk.
