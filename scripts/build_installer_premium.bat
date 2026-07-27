@echo off
REM Build Premium installer via InnoSetup. No 4GB SFX limit.
REM Usage:  scripts\build_installer_premium.bat  signed  OR  internal
REM
REM Prereq: backend built + desktop built + premium_assets bootstrapped, and each
REM artifact carries a BUILD_RECEIPT written by its build wrapper. The clean sealed
REM premium_stage is composed by scripts\release\compose_cli -- no additive robocopy.
REM
REM Build mode is MANDATORY, validated by scripts\release\installer_gate:
REM   signed    Setup + uninstaller Authenticode-signed via the env contract below.
REM   internal  unsigned; named INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE by ISCC.
REM             Refused when release-status.json marks the release distributable.
REM
REM Signed-mode env contract:
REM   KALI_SIGN_PFX                 path to the .pfx code-signing certificate, OR
REM   KALI_SIGN_THUMBPRINT          Windows store / HSM cert thumbprint
REM   KALI_SIGN_PFX_PASS            .pfx password, if any
REM   KALI_SIGN_EXPECTED_THUMBPRINT expected signer thumbprint to verify against
REM   KALI_SIGN_TR_URL             RFC-3161 timestamp URL, defaulted below

setlocal enableextensions
cd /d "%~dp0\.."

REM ---- Version comes from the .iss single source of truth ------------------
set "APPVER="
for /f tokens^=2^ delims^=^" %%V in ('findstr /b /c:"#define AppVersion" scripts\installer_premium.iss') do set "APPVER=%%V"
if not defined APPVER (
    echo ERROR: could not read AppVersion from scripts\installer_premium.iss
    exit /b 1
)
set "SETUP_EXE=dist_premium\installer\KALI-Premium-Setup-%APPVER%.exe"
echo Building version %APPVER%

REM ---- Build mode: signed or internal is MANDATORY, no default -------------
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
set "MODE=%~1"
if not defined MODE (
    echo ERROR: build mode required. Usage: build_installer_premium.bat signed^|internal
    exit /b 1
)
REM %PY% is unquoted in the for/f command on purpose: a for/f command that STARTS
REM with a quote is mis-parsed by cmd. The venv path has no spaces.
set "VMODE="
for /f "usebackq delims=" %%M in (`%PY% -m scripts.release.installer_gate resolve-mode "%MODE%" "release-status.json"`) do set "VMODE=%%M"
if not defined VMODE (
    echo ERROR: installer_gate rejected build mode "%MODE%". Unknown, or internal while distributable=true.
    exit /b 1
)
set "MODE=%VMODE%"
set "GIT_SHA="
for /f "usebackq delims=" %%G in (`git rev-parse HEAD`) do set "GIT_SHA=%%G"
echo Build mode: %MODE%

REM ---- Resolve signtool.exe, needed only for a signed build ----------------
REM Same order as scripts\release\signing_gate.resolve_signtool: explicit env, then
REM PATH, then Windows Kits. The result is exported back into KALI_SIGN_SIGNTOOL so
REM the composer signs with the SAME binary this script verified with.
set "SIGNTOOL="
if defined KALI_SIGN_SIGNTOOL set "SIGNTOOL=%KALI_SIGN_SIGNTOOL%"
if not defined SIGNTOOL for %%S in (signtool.exe) do if not defined SIGNTOOL set "SIGNTOOL=%%~$PATH:S"
if not defined SIGNTOOL if exist "C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe" set "SIGNTOOL=C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
if defined SIGNTOOL set "KALI_SIGN_SIGNTOOL=%SIGNTOOL%"
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
    echo Run first: python scripts\build_backend_premium.py
    exit /b 1
)
if not exist "src-tauri\target\release\kali-desktop.exe" (
    echo ERROR: desktop release exe not built yet.
    echo Run first: python scripts\build_desktop_premium.py
    exit /b 1
)

REM ---- Validate the .iss wiring before composing ---------------------------
"%PY%" -m scripts.release.installer_gate verify-iss scripts\installer_premium.iss
if errorlevel 1 ( echo ERROR: installer_premium.iss failed the wiring gate. & exit /b 1 )

REM ---- Compose a clean sealed stage, replacing additive robocopy -----------
REM The transactional composer copies fresh backend/desktop + the premium_assets
REM SoT + install-webview2.ps1 into a clean premium_stage.next, drops declared dead
REM weight, materializes HF links, signs inner EXEs for a signed build or leaves
REM them unsigned, seals STAGE_MANIFEST.json last, verifies it, then swaps it into
REM premium_stage rollback-safely. Stale or deleted files cannot survive.
echo Composing sealed premium_stage %MODE% ...
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
echo Output:  %SETUP_EXE%  plus .bin slices, DiskSpanning
echo This takes 15-30 minutes for ~9 GB content. Be patient.
echo.

REM ---- ISCC defines --------------------------------------------------------
REM signed builds pass /DSignSetup plus a named SignTool command; internal builds
REM pass /DInternal so the Setup AND every slice are named INTERNAL at compile time.
REM In the SignTool command $q is an embedded quote and $f is the file to sign.
set "DEFINES="
if /I "%MODE%"=="signed" (
    if not defined SIGNTOOL ( echo ERROR: signed build requires signtool.exe. & exit /b 1 )
    if defined KALI_SIGN_THUMBPRINT (
        set DEFINES=/DSignSetup "/Skali=$q%SIGNTOOL%$q sign /fd SHA256 /tr $q%KALI_SIGN_TR_URL%$q /td SHA256 /sha1 %KALI_SIGN_THUMBPRINT% $f"
    ) else (
        if not defined KALI_SIGN_PFX ( echo ERROR: signed build requires KALI_SIGN_THUMBPRINT or KALI_SIGN_PFX. & exit /b 1 )
        if defined KALI_SIGN_PFX_PASS (
            set DEFINES=/DSignSetup "/Skali=$q%SIGNTOOL%$q sign /fd SHA256 /tr $q%KALI_SIGN_TR_URL%$q /td SHA256 /f $q%KALI_SIGN_PFX%$q /p $q%KALI_SIGN_PFX_PASS%$q $f"
        ) else (
            set DEFINES=/DSignSetup "/Skali=$q%SIGNTOOL%$q sign /fd SHA256 /tr $q%KALI_SIGN_TR_URL%$q /td SHA256 /f $q%KALI_SIGN_PFX%$q $f"
        )
    )
)
if /I "%MODE%"=="internal" (
    set "DEFINES=/DInternal"
    set "SETUP_EXE=dist_premium\installer\KALI-Premium-Setup-%APPVER%-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.exe"
)

"%ISCC%" %DEFINES% scripts\installer_premium.iss
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build FAILED with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)

if not exist "%SETUP_EXE%" (
    echo ERROR: expected installer not found: %SETUP_EXE%
    echo ISCC reported success. Version mismatch between .iss and this script?
    exit /b 1
)

if /I "%MODE%"=="signed" (
    REM ISCC signed the Setup and uninstaller. Re-verify the final Setup with the
    REM same structured Authenticode gate: exact thumbprint, valid chain, timestamp.
    "%PY%" -m scripts.release.installer_gate verify-setup "%SETUP_EXE%" "%KALI_SIGN_EXPECTED_THUMBPRINT%"
    if errorlevel 1 ( echo ERROR: structured signature verify failed for the Setup. & exit /b 1 )
    echo [sign] Setup and uninstaller signed and structurally verified.
) else (
    REM Internal naming was done by ISCC OutputBaseFilename. Just drop the marker.
    "%PY%" -m scripts.release.installer_gate write-marker "dist_premium\installer" "%APPVER%"
    if errorlevel 1 ( echo ERROR: internal marker write failed. & exit /b 1 )
    echo [internal] Setup and slices named INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.
)

echo.
echo ============================================
echo   Build complete. mode: %MODE%
echo ============================================
echo InnoSetup produced a DiskSpanning set. Ship ALL of these together, zip them:
dir dist_premium\installer\KALI-Premium-Setup-%APPVER%*

endlocal
exit /b 0
