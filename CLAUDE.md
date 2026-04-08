# Jarvis 2026

Personal AI Command Center — voice-controlled agent orchestrator.

## Tech Stack
- Backend: Python 3.12+ / FastAPI
- Package manager: uv
- Tests: pytest (asyncio_mode=auto)
- Linting: ruff + mypy

## Commands
- `make install` — install dependencies
- `make dev` — run dev server
- `make test` — run tests
- `make lint` — check code quality

## Architecture
- `kernel/` — core Python backend (event bus, config, plugin registry, DB)
- `agents/` — agent implementations with manifest.yaml files
- `config/jarvis.yaml` — main configuration
- See `docs/superpowers/specs/2026-04-08-jarvis-2026-design.md` for full spec

## Conventions
- Type hints on all functions
- Google-style docstrings for public functions
- No print() — use logging
- Specific exceptions, not bare except
- Tests in tests/ mirroring source structure
