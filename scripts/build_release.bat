@echo off
echo ============================================
echo   KALI Release Builder
echo ============================================
echo.

cd /d %~dp0\..
set ROOT=%CD%

echo [1/4] Building Python backend (PyInstaller)...
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64 >nul 2>&1
uv run python scripts/build_backend.py
if %ERRORLEVEL% NEQ 0 (
    echo FAILED: Python backend build
    exit /b 1
)
echo.

echo [2/4] Building Tauri desktop app...
set PATH=%USERPROFILE%\.cargo\bin;%PATH%
npx tauri build
if %ERRORLEVEL% NEQ 0 (
    echo FAILED: Tauri build
    exit /b 1
)
echo.

echo [3/4] Copying files to dist...
copy /Y "src-tauri\target\release\kali-desktop.exe" "dist\" >nul
echo   kali-desktop.exe copied
echo.

echo [4/4] Building installer...
where makensis >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo NSIS not found. Install: winget install NSIS.NSIS
    echo Skipping installer build.
    echo.
    echo === Files ready in dist/ ===
    dir dist\*.exe
    exit /b 0
)
cd scripts
makensis installer.nsi
cd ..
echo.

echo ============================================
echo   Build Complete!
echo ============================================
echo.
dir dist\*.exe
echo.
echo Share dist\KALI-Setup-0.1.0.exe with friends!
