# KALI

**Voice-first AI agent creator for non-tech users.** Desktop (Tauri + FastAPI) → Mobile → Hardware device. Distribution via UGC loop (create agent by voice → share reel → friends install). Agent Skills native (Anthropic open standard).

See [VISION.md](VISION.md) for product thesis and [docs/architecture/](docs/architecture/) for C4 diagrams.

## Tech Stack
- Backend: Python 3.12+ / FastAPI, PyInstaller onedir for distribution
- Frontend: Tauri 2.x + React 19 + TypeScript + Zustand
- Voice: F5-TTS Russian (local GPU) + ElevenLabs (cloud fallback), faster-whisper STT, Silero VAD, OpenWakeWord
- LLM: Claude / OpenAI / Google / DeepSeek via LLM Router
- Package manager: uv (PyTorch cu128 index for RTX 50-series)
- Tests: pytest (asyncio_mode=auto)
- Linting: ruff + mypy

## Commands
- `make install` — install dependencies
- `make dev` — run dev server
- `make test` — run tests
- `make lint` — check code quality
- `uv run --with pyinstaller python scripts/build_backend_premium.py` — build Premium backend
- `scripts\build_installer_premium.bat` — build InnoSetup Premium installer (DiskSpanning)

## Architecture
- `kernel/` — core Python backend (event bus, config, plugin registry, DB, voice, skills, sandbox, builder)
- `agents/` — agent implementations (dual format: legacy `manifest.yaml` + new `SKILL.md`)
- `ui/` — React Tauri shell (modes: Chat, Agent Store, Activity, Builder upcoming)
- `config/kali.yaml` — main configuration
- `models/` — voice models (gitignored): F5 checkpoint, reference WAVs, FFmpeg DLLs
- See [docs/architecture/README.md](docs/architecture/README.md) for C4 diagrams
- See [docs/superpowers/plans/](docs/superpowers/plans/) for active implementation plans
- See [docs/superpowers/specs/2026-04-08-jarvis-2026-design.md](docs/superpowers/specs/2026-04-08-jarvis-2026-design.md) for original spec

## Conventions
- Type hints on all functions
- Google-style docstrings for public functions
- No print() — use logging
- Specific exceptions, not bare except
- Tests in tests/ mirroring source structure
