# Prod-Ready Desktop Handoff (2026-04-14)

## Goal

Ship a Windows Desktop build that friends and colleagues can install and test with minimal manual setup.

## Completed In This Pass

- Unified the canonical backend port to `3005` across runtime defaults, config, tests, and user-facing docs.
- Hardened backend startup defaults:
  - `kernel/__main__.py` and `kernel/main.py` already use env-driven `KALI_HOST` / `KALI_PORT`
  - config default now matches the Desktop runtime (`127.0.0.1:3005`)
- Bundled the core offline voice models into the NSIS installer:
  - `jarvis_v2.onnx`
  - `jarvis_v2.index`
  - `vec-768-layer-12.onnx`
  - `rmvpe.onnx`
- Hardened the release pipeline:
  - `scripts/build_release.bat` now fails fast if the required voice models are missing
  - `scripts/build_release.bat` now uses repo-local `.uv-cache`
  - `scripts/build_release.bat` now uses `call npx tauri build` so batch execution returns to the remaining steps
  - `scripts/build_release.bat` now resolves NSIS via explicit `C:\Program Files (x86)\NSIS\makensis.exe` when needed
  - release build now copies the voice models into `dist/models`
- Hardened Tauri build commands:
  - `src-tauri/tauri.conf.json` now uses `cmd /c npm --prefix ui run dev`
  - `src-tauri/tauri.conf.json` now uses `cmd /c npm --prefix ui run build`
- Hardened the Tauri desktop shell:
  - backend health check now uses `http://127.0.0.1:3005/health`
  - desktop startup injects `KALI_HOST`, `KALI_PORT`, `KALI_CORS_ORIGINS`
  - if a sibling `models` directory exists, desktop startup injects `KALI_MODELS_DIR`
  - backend stdout/stderr are redirected to `%APPDATA%/KALI/logs/`
  - startup now waits briefly for backend health and logs a failure hint if it never becomes healthy
  - Windows startup uses `CREATE_NO_WINDOW` for the backend child process
- Tightened Desktop CSP:
  - removed the old `3002` dependency from Tauri CSP
  - added explicit `127.0.0.1:3005` HTTP/WS allowances
- Updated the UI runtime fallback:
  - default API base URL is now `http://127.0.0.1:3005`
  - `VoiceStatus` typing now includes richer readiness fields
- Updated tester-facing docs:
  - `README.md`
  - `docs/SETUP_GUIDE.md`
  - both now point testers to `dist/KALI-Setup-0.1.0.exe`
  - both now mention `%APPDATA%/KALI/logs/` for backend failures
- Synced tests with the current runtime defaults:
  - config default port expectations updated to `3005`
  - wake-word default threshold expectation updated to `0.3`
- Built fresh release artifacts:
  - `dist/kali-backend.exe`
  - `dist/kali-desktop.exe`
  - `dist/models/*`
  - `dist/KALI-Setup-0.1.0.exe`

## Files Changed In This Pass

- `scripts/installer.nsi`
- `scripts/build_backend.py`
- `scripts/build_release.bat`
- `src-tauri/src/lib.rs`
- `src-tauri/tauri.conf.json`
- `config/kali.yaml`
- `kernel/models.py`
- `ui/src/api/runtime.ts`
- `ui/src/api/types.ts`
- `README.md`
- `docs/SETUP_GUIDE.md`
- `tests/conftest.py`
- `tests/kernel/test_config_manager.py`
- `tests/kernel/test_main.py`
- `tests/kernel/test_models.py`
- `tests/kernel/test_wake_word.py`
- `tests/e2e/test_full_flow.py`

## Verification Completed

- Python syntax check passed:
  - `python -m py_compile kernel\\main.py kernel\\__main__.py kernel\\runtime_paths.py kernel\\model_downloader.py kernel\\voice\\tts.py kernel\\voice\\tts_engine.py kernel\\models.py`
- TypeScript check passed:
  - `cmd /c npx tsc --noEmit`
- Rust Desktop shell check passed:
  - `cargo check` in `src-tauri/`
- Manual smoke script passed:
  - config load returns port `3005`
  - `/config` returns port `3005`
  - `/voice/status` returns `200`
- Release artifacts built successfully:
  - `dist/kali-backend.exe` at `307,489,244` bytes
  - `dist/kali-desktop.exe` at `15,151,616` bytes
  - `dist/KALI-Setup-0.1.0.exe` at `978,093,984` bytes
  - `dist/models/` contains the 4 required runtime voice files

## Test Caveats

- Targeted `pytest` is still unreliable in this local Windows environment because of temp-directory ACL issues.
- Useful signal:
  - `tests/kernel/test_models.py` passed
  - `tests/kernel/test_wake_word.py` passed
- Untrusted signal:
  - tests that rely on `tmp_path` / temp cleanup hit local permission failures during setup or session cleanup
- Recommendation:
  - re-run pytest on a cleaner Windows environment or inside the intended packaging/test VM

## Remaining Work For Claude Code

1. Run a clean-install smoke test on a fresh Windows machine or VM.
   - Install `dist/KALI-Setup-0.1.0.exe`
   - Launch KALI from Start Menu/Desktop
   - Confirm backend auto-start works from `Program Files`
   - Confirm logs appear in `%APPDATA%/KALI/logs/`
   - Confirm `/voice/status` reports a healthy ready state
   - Confirm TTS audio actually plays inside Tauri

2. Reproduce and finish the remaining runtime issues from the latest daily log if they still exist.
   - TTS not audible in Tauri
   - Voice activation not working
   - Backend auto-start failures in installed mode

3. Decide whether to keep the current fully bundled model strategy.
   - Current patch favors offline readiness and simple tester install
   - Tradeoff: installer size increases significantly

4. Audit the remaining historical plan/spec docs if the team wants one source of truth everywhere.
   - There are still dated plan/spec markdown files under `docs/superpowers/plans/` that mention `8000`
   - They are historical documents, so I did not rewrite them automatically

5. Optional but high-value polish after the installer is proven stable.
   - Show backend log path in the UI
   - Add a desktop readiness panel (`backend`, `voice`, `models`, `api keys`, `integrations`)
   - Hide or clearly label mock/placeholder agents in tester builds

## Context Notes

- The worktree was already dirty before this pass.
- Be careful not to revert unrelated user changes in:
  - `kernel/voice/pipeline.py`
  - `kernel/voice/recorder.py`
  - `kernel/voice/vad.py`
  - `kernel/voice/wake_word.py`
  - `kernel/voice/tts_engine.py`
  - `src-tauri/src/lib.rs`
  - `pyproject.toml`
  - `uv.lock`
  - `services/nano-qwen3tts-vllm`
- The most important next checkpoint is not another code change. It is a clean installer run on a second Windows machine.
