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
REM   KALI_SIGN_SIGNTOOL            optional explicit signtool.exe; when unset it is
REM                                 resolved by scripts\release\installer_gate and
REM                                 exported for the composer

setlocal enableextensions
cd /d "%~dp0\.."

REM ---- Version comes from the .iss single source of truth ------------------
set "APPVER="
for /f tokens^=2^ delims^=^" %%V in ('findstr /b /c:"#define AppVersion" scripts\installer_premium.iss') do set "APPVER=%%V"
if not defined APPVER (
    echo ERROR: could not read AppVersion from scripts\installer_premium.iss
    exit /b 1
)
REM H6-5: ISCC never writes over the live installer dir (it could still hold slices
REM from a previous, larger build). It builds into a clean next-* dir, the exact
REM artifact set is sealed, and only then is it promoted rollback-safely.
set "OUTNEXT=dist_premium\installer.next-1"
set "SETUP_NAME=KALI-Premium-Setup-%APPVER%.exe"
set "SETUP_EXE=%OUTNEXT%\%SETUP_NAME%"
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
REM This script keeps NO path list of its own: it asks the single python resolver
REM (scripts\release\signing_gate.resolve_signtool via installer_gate) and exports the
REM answer, so the composer signs with the SAME binary this script verified with.
REM %PY% is unquoted in the for/f on purpose: a for/f command that STARTS with a
REM quote is mis-parsed by cmd. The venv path has no spaces.
REM The exports below must stay OUTSIDE any parenthesised block: %SIGNTOOL% inside a
REM block would expand at parse time, i.e. before the for/f ever assigns it.
set "SIGNTOOL="
if not defined KALI_SIGN_TR_URL set "KALI_SIGN_TR_URL=http://timestamp.digicert.com"
if /I not "%MODE%"=="signed" goto :signtool_done
for /f "usebackq delims=" %%S in (`%PY% -m scripts.release.installer_gate resolve-signtool`) do set "SIGNTOOL=%%S"
if defined SIGNTOOL set "KALI_SIGN_SIGNTOOL=%SIGNTOOL%"
REM A signed build aborts HERE, before the multi-GB compose signs anything.
if not defined SIGNTOOL (
    echo ERROR: signed build requires signtool.exe. Install the Windows SDK or set KALI_SIGN_SIGNTOOL.
    exit /b 1
)
if not defined KALI_SIGN_THUMBPRINT if not defined KALI_SIGN_PFX (
    echo ERROR: signed build requires KALI_SIGN_THUMBPRINT or KALI_SIGN_PFX.
    exit /b 1
)
:signtool_done

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
    set "SETUP_NAME=KALI-Premium-Setup-%APPVER%-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.exe"
    set "DEFINES=/DInternal"
)
if /I "%MODE%"=="internal" set "SETUP_EXE=%OUTNEXT%\KALI-Premium-Setup-%APPVER%-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.exe"

REM H7-5: ISCC, the artifact seal and the promote all happen inside ONE python process
REM that holds the installer OS-lock and journals every window, so a crash can never
REM leave the live installer directory half-replaced and two ISCC runs cannot overlap.
REM The signed Authenticode check is passed IN, so it gates the promote instead of
REM running after the live installer directory has already been replaced.
set "MARKER="
if /I "%MODE%"=="internal" set "MARKER=--internal %APPVER%"
if /I "%MODE%"=="signed" set "MARKER=--verify %KALI_SIGN_EXPECTED_THUMBPRINT%"
"%PY%" -m scripts.release.installer_gate build-output "%MODE%" "dist_premium" "%SETUP_NAME%" "%ISCC%" "scripts\installer_premium.iss" %MARKER% %DEFINES%
if errorlevel 1 (
    echo.
    echo ERROR: installer output build/seal/promote failed.
    exit /b 1
)
set "SETUP_EXE=dist_premium\installer\%SETUP_NAME%"

if /I "%MODE%"=="signed" (
    REM build-output already verified the Setup structurally BEFORE promoting it:
    REM exact thumbprint, valid chain, timestamp. A failure there left the previous
    REM installer directory in place.
    echo [sign] Setup and uninstaller signed and structurally verified before promote.
) else (
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
