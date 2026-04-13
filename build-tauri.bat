@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cd /d C:\Users\User\Desktop\Jarvis
echo === Starting Tauri Build ===
npx tauri build
echo === Build Complete (exit code: %ERRORLEVEL%) ===
