@echo off
REM Build Premium installer via InnoSetup (replaces 7z SFX — no 4GB limit).
REM Usage:  scripts\build_installer_premium.bat <signed|internal>
REM
REM Prereq: backend built (scripts\build_backend_premium.py) + desktop built +
REM the premium_assets source-of-truth bootstrapped (scripts\release\asset_bootstrap).
REM The clean sealed premium_stage is COMPOSED by the transactional composer
REM (scripts\release\compose_cli) — this script no longer stages with an additive
REM robocopy /E (which let stale/deleted files survive across builds).
REM
REM Build mode is MANDATORY (C7/OPUS-201), validated by scripts\release\installer_gate:
REM   signed    — Setup + uninstaller Authenticode-signed (needs the env vars below);
REM               refused unless a cert + signtool are present (no silent unsigned).
REM   internal  — unsigned; output renamed to ...-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.
REM               Refused when release-status.json marks the release distributable.
REM
REM Signed-mode env vars:
REM   KALI_SIGN_CERT    path to the .pfx code-signing certificate
REM   KALI_SIGN_PASS    certificate password (optional if the .pfx has none)
REM   KALI_SIGN_TR_URL  RFC-3161 timestamp URL (default below)

setlocal enableextensions
cd /d "%~dp0\.."

REM ---- Version comes from the .iss (single source of truth) ----------------
set "APPVER="
for /f tokens^=2^ delims^=^" %%V in ('findstr /b /c:"#define AppVersion" scripts\installer_premium.iss') do set "APPVER=%%V"
if not defined APPVER (
    echo ERROR: could not read AppVersion from scripts\installer_premium.iss
    exit /b 1
)
set "SETUP_EXE=dist_premium\installer\KALI-Premium-Setup-%APPVER%.exe"
echo Building version %APPVER%

REM ---- Build mode (C7/OPUS-201): signed|internal is MANDATORY (no default) --
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
set "MODE=%~1"
if not defined MODE (
    echo ERROR: build mode required — usage: build_installer_premium.bat ^<signed^|internal^>
    exit /b 1
)
set "VMODE="
for /f "usebackq delims=" %%M in (`"%PY%" -m scripts.release.installer_gate resolve-mode "%MODE%" "release-status.json"`) do set "VMODE=%%M"
if not defined VMODE (
    echo ERROR: installer_gate rejected build mode "%MODE%" ^(unknown, or internal while distributable=true^).
    exit /b 1
)
set "MODE=%VMODE%"
set "GIT_SHA="
for /f "usebackq delims=" %%G in (`git rev-parse HEAD`) do set "GIT_SHA=%%G"
echo Build mode: %MODE%

REM ---- Resolve signtool.exe (needed only for a signed build) ----------------
set "SIGNTOOL="
for %%S in (signtool.exe) do if not defined SIGNTOOL set "SIGNTOOL=%%~$PATH:S"
if not defined SIGNTOOL if exist "C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe" set "SIGNTOOL=C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
if not defined KALI_SIGN_TR_URL set "KALI_SIGN_TR_URL=http://timestamp.digicert.com"

set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\iscc.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\iscc.exe"
if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\iscc.exe"
if exist "C:\Program Files\Inno Setup 6\iscc.exe" set "ISCC=C:\Program Files\Inno Setup 6\iscc.exe"
if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 not found.
    echo Install it: winget install -e --id JRSoftware.InnoSetup
    exit /b 1
)

if not exist "dist_premium\kali-backend\kali-backend.exe" (
    echo ERROR: backend not built yet.
    echo Run first: uv run --with pyinstaller python scripts\build_backend_premium.py
    exit /b 1
)
if not exist "src-tauri\target\release\kali-desktop.exe" (
    echo ERROR: desktop release exe not built yet.
    echo Run first: npm --prefix ui exec -- tauri build
    exit /b 1
)

REM ---- Compose a clean, sealed stage (C5/C7 — replaces additive robocopy) ---
REM The transactional composer copies fresh backend/desktop + the premium_assets
REM SoT + install-webview2.ps1 into a clean premium_stage.next-*, drops declared
REM dead weight, materializes HF links, signs inner EXEs (signed) or leaves them
REM unsigned (internal), seals STAGE_MANIFEST.json LAST, verifies it, then swaps
REM it into premium_stage rollback-safely. Stale/deleted files cannot survive.
echo Composing sealed premium_stage ^(%MODE%^)...
"%PY%" -m scripts.release.compose_cli "%MODE%" "%APPVER%" "%GIT_SHA%"
if errorlevel 1 (
    echo ERROR: stage compose failed.
    exit /b 1
)
echo.

echo ============================================
echo   Building KALI Premium installer via InnoSetup
echo ============================================
echo Source:  dist_premium\premium_stage\
echo Output:  %SETUP_EXE% ^(+ .bin slices — DiskSpanning^)
echo This takes ~15-30 minutes for ~9 GB content. Be patient.
echo.

REM signed → sign Setup + uninstaller at compile via a named Inno SignTool.
REM ($q = an embedded quote, $f = the file to sign — Inno's SignTool syntax.)
set "SIGN_DEFINE="
if /I "%MODE%"=="signed" (
    if not defined KALI_SIGN_CERT ( echo ERROR: signed build requires KALI_SIGN_CERT. & exit /b 1 )
    if not defined SIGNTOOL ( echo ERROR: signed build requires signtool.exe. & exit /b 1 )
    if defined KALI_SIGN_PASS (
        set SIGN_DEFINE=/DSignSetup "/Skali=$q%SIGNTOOL%$q sign /fd SHA256 /tr $q%KALI_SIGN_TR_URL%$q /td SHA256 /f $q%KALI_SIGN_CERT%$q /p $q%KALI_SIGN_PASS%$q $f"
    ) else (
        set SIGN_DEFINE=/DSignSetup "/Skali=$q%SIGNTOOL%$q sign /fd SHA256 /tr $q%KALI_SIGN_TR_URL%$q /td SHA256 /f $q%KALI_SIGN_CERT%$q $f"
    )
)

"%ISCC%" %SIGN_DEFINE% scripts\installer_premium.iss
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build FAILED with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)

if not exist "%SETUP_EXE%" (
    echo ERROR: expected installer not found: %SETUP_EXE%
    echo ^(ISCC reported success — version mismatch between .iss and this script?^)
    exit /b 1
)

if /I "%MODE%"=="signed" (
    REM ISCC already signed Setup + uninstaller; verify the chain fail-closed.
    "%SIGNTOOL%" verify /pa /v "%SETUP_EXE%"
    if errorlevel 1 ( echo ERROR: signtool verify /pa failed for the Setup. & exit /b 1 )
    echo [sign] Setup + uninstaller signed and verified.
) else (
    REM INTERNAL: rename to the explicit DO-NOT-DISTRIBUTE artifact + marker.
    "%PY%" -m scripts.release.installer_gate mark-internal "%SETUP_EXE%" "%APPVER%"
    if errorlevel 1 ( echo ERROR: internal-marking failed. & exit /b 1 )
    echo [internal] output renamed to ...-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.
)

echo.
echo ============================================
echo   Build complete! (mode: %MODE%)
echo ============================================
echo InnoSetup produced a DiskSpanning set — ship ALL of these together (zip them):
dir dist_premium\installer\KALI-Premium-Setup-%APPVER%*

endlocal
exit /b 0
