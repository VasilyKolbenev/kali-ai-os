@echo off
echo ============================================
echo   KALI Release Builder
echo ============================================
echo.

cd /d %~dp0\..
set ROOT=%CD%
set UV_CACHE_DIR=%ROOT%\.uv-cache
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%"

echo [0/4] Verifying bundled voice models...
for %%F in (jarvis_v2.onnx jarvis_v2.index vec-768-layer-12.onnx rmvpe.onnx) do (
    if not exist "models\%%F" (
        echo FAILED: models\%%F not found
        exit /b 1
    )
)
echo   Voice models found
echo.

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
call npx tauri build
if %ERRORLEVEL% NEQ 0 (
    echo FAILED: Tauri build
    exit /b 1
)
echo.

echo [3/4] Copying runtime files to dist...
copy /Y "src-tauri\target\release\kali-desktop.exe" "dist\" >nul
echo   kali-desktop.exe copied
if not exist "dist\models" mkdir "dist\models"
copy /Y "models\jarvis_v2.onnx" "dist\models\" >nul
copy /Y "models\jarvis_v2.index" "dist\models\" >nul
copy /Y "models\vec-768-layer-12.onnx" "dist\models\" >nul
copy /Y "models\rmvpe.onnx" "dist\models\" >nul
echo   voice models copied
echo.

echo [4/4] Building installer...
set "NSIS_EXE="
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "NSIS_EXE=C:\Program Files (x86)\NSIS\makensis.exe"
if "%NSIS_EXE%"=="" (
    where makensis >nul 2>&1
    if %ERRORLEVEL% EQU 0 set "NSIS_EXE=makensis"
)
if "%NSIS_EXE%"=="" (
    echo NSIS not found. Install: winget install NSIS.NSIS
    echo Skipping installer build.
    echo.
    echo === Files ready in dist/ ===
    dir dist\*.exe
    exit /b 0
)
cd scripts
"%NSIS_EXE%" installer.nsi
cd ..
echo.

echo ============================================
echo   Build Complete!
echo ============================================
echo.
dir dist\*.exe
echo.
echo Share dist\KALI-Setup-0.1.0.exe with friends!
