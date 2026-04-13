# KALI Desktop App — Full Production Design

**Date:** 2026-04-12
**Status:** Approved (v2, post-review)
**Goal:** Native Windows desktop application without WSL dependency.

## Architecture

```
KALI.exe (Tauri)
├── Tauri Shell (Rust)
│   ├── System tray icon + context menu
│   ├── Global hotkey (Ctrl+Space = push-to-talk, configurable)
│   ├── Window management (minimize to tray)
│   ├── Service manager (Windows Job Objects)
│   │   ├── Python kernel (FastAPI, port 3005)
│   │   └── Python TTS+RVC server (Flask, port 3002)
│   └── First-run setup (model download + progress UI)
└── React UI (bundled in Tauri webview)
    ├── Chat, Avatar, Dashboard, Agents
    └── API calls via configurable base URLs
```

## 1. RVC: PyTorch → ONNX

**Current:** `infer_rvc_python` → fairseq → WSL only
**New:** ONNX Runtime GPU → native Windows

### Export steps (one-time, from WSL):
1. Clone RVC WebUI export module
2. Export `jarvis_v1_300e_4500s_best_epoch.pth` → `jarvis_v1.onnx`
3. Download from HuggingFace:
   - `vec-768-layer-12.onnx` — HuBERT ([MidFord327/Hubert-Base-ONNX](https://huggingface.co/MidFord327/Hubert-Base-ONNX))
   - `rmvpe.onnx` — pitch estimator ([lj1995/VoiceConversionWebUI](https://huggingface.co/lj1995/VoiceConversionWebUI/blob/main/rmvpe.onnx))
4. If pre-built ONNX not available → export manually via torch.onnx.export

### Realistic performance (post-review):

| Step | Current (WSL PyTorch) | ONNX (estimated) |
|------|----------------------|-------------------|
| Silero TTS | 0.06s | 0.06s |
| HuBERT features | included in RVC | ~0.1s |
| RMVPE pitch | included in RVC | ~0.1s |
| RVC voice conversion | 0.9s total | ~0.2s |
| HTTP TTS→RVC | 0.5s overhead | 0s (in-process) |
| **Total** | **~1.5s** | **~0.5s** |

Note: actual ONNX speedup is 1.5-3x, not 10x. Must benchmark after export.

## 2. Merged TTS + RVC Server

Single `services/tts/server.py` runs Silero + ONNX RVC in-process.

**Framework:** Flask (kept for TTS server — simple, no async needed for sync inference pipeline). Kernel stays FastAPI.

**Dependencies (Windows native, pip):**
- `torch` (CPU only, for Silero)
- `onnxruntime-gpu` (CUDA) or `onnxruntime-directml` (AMD/Intel)
- `faiss-cpu` (index search)
- `soundfile`, `numpy`, `flask`, `flask-cors`
- `librosa` (audio resampling if needed)

## 3. Tauri Desktop Shell

### Plugins:
- `tauri-plugin-shell` — spawn Python child processes
- `tauri-plugin-global-shortcut` — Ctrl+Space hotkey (configurable)
- `tauri-plugin-autostart` — optional Windows startup

### Service manager (Rust):
- Use **Windows Job Objects** (`windows-rs` crate) — child processes auto-terminate when parent exits
- Health-check polling: GET `/health` every 2s until ready, timeout 30s
- Status shown in UI: "Starting kernel...", "Starting TTS...", "Ready"
- If service fails: show error in UI, app works in text-only mode (graceful degradation)

### Global hotkey:
- Default: **Ctrl+Space** (not bare Space — avoids system-wide conflicts)
- User-configurable via settings
- Registers/unregisters on app focus changes

### Window behavior:
- Close button → minimize to system tray
- Tray menu: Show/Hide, Settings, Quit
- Quit from tray → graceful shutdown (term child processes)

## 4. UI Changes for Tauri

### Configurable URLs:
- `ChatInput.tsx` TTS_URL → read from env/config, not hardcoded
- `client.ts` BASE_URL → configurable
- `websocket.ts` WS_URL → configurable
- Tauri injects config via `window.__KALI_CONFIG__` at startup

### CORS/CSP:
- Kernel CORS: restrict to `tauri://localhost` and `http://localhost:1420` (dev)
- Remove `allow_origins=["*"]` in production builds

## 5. Installer

### Strategy:
- `cargo tauri build` → `.msi` installer
- Bundles: Tauri binary + React UI
- **Python:** Use `python-build-standalone` (portable, ~40MB) bundled in installer
- **Python deps:** `uv sync` on first run (venv created in app data dir)
- **ONNX models:** Downloaded on first run (not bundled — too large)

### First-run flow:
1. App launches → detects no models in `%APPDATA%/KALI/models/`
2. Shows progress dialog: "Downloading JARVIS voice model..."
3. Downloads with resume support, SHA256 checksum validation
4. ~750MB total (HuBERT 380MB + RMVPE 362MB + RVC ~60MB)
5. On completion → starts services normally

### Installer size:
- Tauri binary + UI: ~15MB
- Portable Python: ~40MB
- Total installer: ~55MB (models downloaded separately)

## 6. Auto-updates (deferred)

- `tauri-plugin-updater` for delta updates via GitHub Releases
- Scope for v1.1, not blocking initial release
- v1.0: manual download from GitHub Releases

## 7. Security

- CORS restricted to Tauri origin in production
- No `allow_origins=["*"]` in packaged builds
- API token between UI and kernel (generated on startup, passed to webview)
- ONNX models verified by SHA256 checksum on download

## 8. FAISS Index Compatibility

- FAISS indexes may differ between Linux/Windows due to BLAS
- On first Windows run: if index load fails, regenerate from model
- Add fallback: RVC works without index (lower quality but functional)

## Implementation Order

1. Export RVC model to ONNX (WSL, one-time)
2. Download HuBERT + RMVPE ONNX models
3. Write ONNX RVC inference (test on Windows Python)
4. Merge into TTS server, benchmark
5. Install Rust toolchain
6. Configure Tauri: service manager, tray, hotkeys
7. Make UI URLs configurable
8. Build desktop app, test end-to-end
9. Create .msi installer
10. First-run model download flow

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| ONNX export fails | Use tts-with-rvc-onnx lib or manual torch.onnx.export |
| Voice quality differs in ONNX | Same weights → should be identical. A/B test. |
| FAISS index incompatible | Regenerate on Windows, or skip index (graceful) |
| Python embedding too large | python-build-standalone ~40MB, acceptable |
| Models download slow | Resume support, progress UI, run once |
