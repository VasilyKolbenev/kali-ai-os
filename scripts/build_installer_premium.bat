@echo off
REM Build Premium installer via InnoSetup (replaces 7z SFX — no 4GB limit).
REM Prereq: backend built (scripts\build_backend_premium.py) + premium_stage\
REM pre-populated with heavy models / .hf_cache (this script re-stages the two
REM volatile build artifacts: kali-backend\ and kali-desktop.exe).
REM LICENSE: models\ffmpeg\ MUST be the LGPL FFmpeg build (NOT GPL) — torchcodec
REM only decodes, so libx264/GPL is never needed. Run scripts\fetch_lgpl_ffmpeg.py
REM --stage to (re)install the BtbN lgpl-shared DLLs + LICENSE.txt (P1.4).
REM Install InnoSetup: winget install -e --id JRSoftware.InnoSetup
REM
REM Optional code signing (5.2): set these env vars to sign the inner exes and
REM the final installer with a timestamped Authenticode signature. When unset
REM the build still runs and produces an UNSIGNED installer (no-op cleanly):
REM   KALI_SIGN_CERT    path to the .pfx code-signing certificate
REM   KALI_SIGN_PASS    certificate password (optional if the .pfx has none)
REM   KALI_SIGN_TR_URL  RFC-3161 timestamp URL (default below)

setlocal enableextensions
cd /d "%~dp0\.."

REM ---- Version comes from the .iss (single source of truth) ----------------
REM NEVER hardcode it here: a stale literal made :sign target a non-existent
REM file, and :sign no-ops (exit 0) on a missing file — so once KALI_SIGN_CERT
REM is set the final installer would ship UNSIGNED while the build reported
REM success. Parse `#define AppVersion "X"` instead.
set "APPVER="
for /f tokens^=2^ delims^=^" %%V in ('findstr /b /c:"#define AppVersion" scripts\installer_premium.iss') do set "APPVER=%%V"
if not defined APPVER (
    echo ERROR: could not read AppVersion from scripts\installer_premium.iss
    exit /b 1
)
set "SETUP_EXE=dist_premium\installer\KALI-Premium-Setup-%APPVER%.exe"
echo Building version %APPVER%

REM ---- Resolve signtool.exe (optional; signing is skipped if absent) --------
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

REM ---- Stage build artifacts (5.3, fail-fast) ------------------------------
REM Re-copy the two volatile build outputs into premium_stage\ so a stale
REM backend/desktop never ships in a (signed) installer. robocopy /E is
REM ADDITIVE — it must NOT be /MIR, which would wipe the pre-staged .hf_cache
REM and models\ that live alongside. robocopy exit code < 8 = success.
echo Staging freshly-built backend into premium_stage...
if not exist "dist_premium\premium_stage" mkdir "dist_premium\premium_stage"
robocopy "dist_premium\kali-backend" "dist_premium\premium_stage\kali-backend" /E /NFL /NDL /NJH /NJS /NP
if errorlevel 8 (
    echo ERROR: staging kali-backend failed ^(robocopy exit code 8 or higher^).
    exit /b 1
)
echo Staging freshly-built kali-desktop.exe into premium_stage...
robocopy "src-tauri\target\release" "dist_premium\premium_stage" kali-desktop.exe /NFL /NDL /NJH /NJS /NP
if errorlevel 8 (
    echo ERROR: staging kali-desktop.exe failed ^(robocopy exit code 8 or higher^).
    exit /b 1
)

REM ---- Drop dead weight from the stage (5.4) -------------------------------
REM ggml-base.bin: leftover whisper.cpp model from the abandoned Rust-native
REM STT path, referenced nowhere in shipped code (STT uses faster-whisper /
REM CTranslate2 model.bin). ~148 MB of dead weight — delete from staging.
REM NOTE: the three silero_vad*.onnx files are each loaded by a different live
REM consumer (Rust ort VAD, faster-whisper vad_filter, OpenWakeWord) and are
REM intentionally NOT deduped here — none is an unused duplicate.
if exist "dist_premium\premium_stage\models\ggml-base.bin" (
    echo Removing dead ggml-base.bin from stage...
    del /f /q "dist_premium\premium_stage\models\ggml-base.bin"
)

REM ---- Sign inner executables (5.2; no-op cleanly without a cert) ----------
call :sign "dist_premium\premium_stage\kali-desktop.exe"
if errorlevel 1 exit /b 1
call :sign "dist_premium\premium_stage\kali-backend\kali-backend.exe"
if errorlevel 1 exit /b 1
echo.

echo ============================================
echo   Building KALI Premium installer via InnoSetup
echo ============================================
echo Source:  dist_premium\premium_stage\
echo Output:  %SETUP_EXE% ^(+ .bin slices — DiskSpanning^)
echo Compression: lzma2/ultra64 (slow but small)
echo.
echo This takes ~15-30 minutes for ~9 GB content. Be patient.
echo.

REM Materialize HF-cache symlinks (vocos/Whisper snapshots -> blobs) into real
REM files before packaging: shipping the symlinks risks dangling links on the
REM user's machine (offline gate then fails to load voice instead of degrading)
REM or double-shipping each model. See scripts\materialize_hf_symlinks.py.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
echo Materializing HF-cache symlinks to real files...
"%PY%" scripts\materialize_hf_symlinks.py "dist_premium\premium_stage"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: HF-cache materialization failed.
    exit /b 1
)
echo.

"%ISCC%" scripts\installer_premium.iss

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build FAILED with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)

REM Sign the final installer (5.2; no-op cleanly without a cert).
REM Fail loudly if the artifact is missing: :sign silently skips absent files,
REM so a wrong path here would ship an unsigned installer as a "successful" build.
if not exist "%SETUP_EXE%" (
    echo ERROR: expected installer not found: %SETUP_EXE%
    echo ^(ISCC reported success — version mismatch between .iss and this script?^)
    exit /b 1
)
call :sign "%SETUP_EXE%"
if errorlevel 1 exit /b 1

echo.
echo ============================================
echo   Build complete!
echo ============================================
echo.
echo InnoSetup produced a DiskSpanning set — the bundle exceeds Inno's
echo ~4.2 GB single-file limit, so slices are MANDATORY, not optional:
echo   .exe   - wizard UI + first slice
echo   .bin   - remaining slices, must sit NEXT TO the .exe
echo.
dir dist_premium\installer\KALI-Premium-Setup-%APPVER%*
echo.
echo Ship ALL of these together (zip them) — a missing .bin breaks the install.

endlocal
exit /b 0

REM ===========================================================================
REM :sign "<file>"  — timestamped Authenticode signing, env-gated.
REM No-ops cleanly (returns 0) when KALI_SIGN_CERT is unset or signtool is
REM missing, so today's unsigned build still succeeds. Signs automatically
REM once Vasily provides the EV cert via KALI_SIGN_CERT (+ optional PASS).
REM ===========================================================================
:sign
if not defined KALI_SIGN_CERT (
    echo [sign] skipped — no cert configured ^(set KALI_SIGN_CERT to enable^)
    goto :eof
)
if not defined SIGNTOOL (
    echo [sign] skipped — signtool.exe not found ^(KALI_SIGN_CERT is set^)
    goto :eof
)
if not exist %1 (
    echo [sign] skipped — file not found: %1
    goto :eof
)
echo [sign] signing %1
if defined KALI_SIGN_PASS (
    "%SIGNTOOL%" sign /fd SHA256 /tr "%KALI_SIGN_TR_URL%" /td SHA256 /f "%KALI_SIGN_CERT%" /p "%KALI_SIGN_PASS%" %1
) else (
    "%SIGNTOOL%" sign /fd SHA256 /tr "%KALI_SIGN_TR_URL%" /td SHA256 /f "%KALI_SIGN_CERT%" %1
)
if errorlevel 1 (
    echo ERROR: signing failed for %1
    exit /b 1
)
goto :eof
