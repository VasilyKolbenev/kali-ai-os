# Changelog

All notable changes to KALI (Personal AI OS) follow
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0-beta] — 2026-04-21

**Strategic pivot: KALI is now native to the [Agent Skills ecosystem](https://agentskills.io).**
Скиллы, созданные в KALI, работают в Claude Code / Cursor / Copilot / VS Code /
Gemini CLI. Скиллы из Anthropic, Microsoft, VoltAgent (1100+) работают в KALI.

### Added

- **Agent Skills spec native support** (SKILL.md)
  - `kernel/skills/loader.py` — YAML frontmatter + Markdown parser
  - `kernel/skills/validator.py` — strict spec compliance
  - `kernel/skills/registry.py` — hybrid builtin + user discovery
  - `kernel/skills/converter.py` — legacy manifest.yaml → SKILL.md migration
- **Multi-source catalog** (GitHub)
  - Default sources: `anthropics/skills`, `microsoft/skills`,
    `VoltAgent/awesome-agent-skills`, `VasilyKolbenev/kali-skills`
  - Trust levels: official / verified / community
  - On-disk cache with 1h TTL + GITHUB_TOKEN support
- **Remote install** with AST safety gate and atomic deploy/rollback
- **Publish flow**: `kali publish <skill>` CLI + UI "Upload" button
- **Sandbox hardening**
  - `SandboxBackend` Protocol (pluggable for future Docker / CubeVM / E2B)
  - `InProcessSandbox` with pre-dispatch permission + rate limit checks
  - `AuditLog` SQLite table (30-day retention, never blocks dispatch)
  - `SandboxHttpClient` with domain whitelist + rate limit + size cap for skills
- **Activity mode** in UI — per-agent stats, filters, recent dispatches
- **Multi-provider AgentBuilder** — OpenAI / Anthropic / Google / DeepSeek
- **Intent Classifier LLM mode** + regex fallback
- **Deployer rollback** on skill deployment failure
- **New REST endpoints**:
  - `GET  /skills/catalog/sources`
  - `GET  /skills/catalog?source=X&q=Y`
  - `POST /skills/catalog/refresh`
  - `POST /skills/install` / `POST /skills/uninstall`
  - `GET  /skills/installed`
  - `POST /skills/validate` / `POST /skills/publish`
  - `GET  /sandbox/health`
  - `GET  /sandbox/audit?hours=N&agent=X&status=Y&limit=N`
  - `GET  /sandbox/stats?hours=N`

### Changed

- `PluginRegistry` now supports dual format (SKILL.md + legacy manifest.yaml)
- `/agents/{name}/execute` routes through `SandboxBackend`:
  - **HTTP 403** on permission denied
  - **HTTP 429** on rate limit exceeded
- Agent Store UI rewritten with source tabs and trust badges
- Default rate limit: 120 requests / 60 seconds per agent
- VISION.md version 0.4.0 → 0.5.0 — Phase 5 & 6 marked DONE

### Fixed

- `multiprocessing.freeze_support()` now at top of entry.py (prevents fork bomb)
- Thread-safe audio recorder queue (`queue.Queue` instead of `asyncio.Queue`)
- Silero VAD cache `PermissionError` on Windows (redirects to temp dir)
- Anti-echo 500ms buffer after TTS playback
- LISTENING timeout 3s (prevents pipeline hang if no speech)
- `.env` loaded from `%APPDATA%/KALI/.env` in frozen mode
- Encoding fixes for Cyrillic filenames in ElevenLabs voice clone upload

### Security

- AST-based safety gate now enforced on:
  - Skill install (from catalog)
  - Skill publish (before bundling)
- All dispatches audited to SQLite with retention policy
- HTTP calls from skills constrained by manifest's `permissions.network.domains`

### Tests

- **141 passing** unit tests across skills + sandbox + plugin_registry modules

### Distribution

- **KALI-Lite-Setup-0.2.0-beta.exe** — 104 MB, NSIS installer
  (ElevenLabs cloud voice, no GPU required)
- **KALI-Premium-Setup-0.2.0-beta.exe** — 3.4 GB, 7z SFX installer
  (F5-TTS Russian local voice, NVIDIA GPU required)

---

## [0.1.0] — 2026-04-13 (first internal release)

### Added

- FastAPI kernel with event bus, plugin registry, scheduler
- Agent Runtime with JSON-RPC subprocess + HTTP protocols
- Voice pipeline: Silero VAD + OpenWakeWord + faster-whisper STT
- JARVIS voice: Silero TTS + ONNX RVC voice conversion
- 15 built-in agents (system, tasks, calendar, weather, email, telegram,
  life-dashboard, smart-home, coding, notion, todoist, github, news, currency,
  water-tracker)
- Tauri 2 desktop shell with React 19 UI
- Dashboard, Agent Panel, Nightstand, Agent Store, Settings modes
- Morning/evening briefing scheduler
- Focus timer, Budget, Routines features
- Full PyInstaller + NSIS distribution pipeline
