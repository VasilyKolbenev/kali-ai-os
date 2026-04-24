# KALI Rust Backend Migration — Architectural Spec

> **Status:** Approved 2026-04-24. Implementation starts with Phase 0.
> **Audience:** Claude (agentic worker) + future maintainers.
> **Supersedes:** None. **Pauses:** `2026-04-26-holographic-design-tokens.md` Chunk 5+ until Phase 3 lands.

---

## 1. Context

KALI's current backend is a Python 3.12 FastAPI application (`kernel/*.py`) bundled for distribution via PyInstaller onedir (Premium build: ~7.84 GB). The Tauri shell (Rust) spawns the bundled executable as a subprocess on app start and kills it on exit.

Three pain points triggered the rewrite:
1. **Distribution bloat** — 7.84 GB is a friction point for non-tech distribution via Google Drive / direct downloads.
2. **Differentiation vs OpenClaw** — OpenClaw is a viral Python-based agent OS targeting developers. KALI chooses Rust to cement the "polished non-tech product" positioning — faster startup, smaller footprint, tighter integration with Tauri.
3. **Operational polish** — Rust's type safety + single-process model reduces class of bugs we've hit in the Python event loop (e.g. `uv run` breaking venv, pyinstaller hidden-imports churn).

## 2. Goals & Non-Goals

**Goals:**
- Replace the Python FastAPI orchestration layer with a Rust implementation embedded in the Tauri main process.
- Preserve every public HTTP + WebSocket contract the current UI consumes (zero UI API rewrites during migration).
- Keep all Python ML code (F5-TTS, faster-whisper, Silero VAD, OpenWakeWord, ruaccent, text preprocessor) as-is. Python runs as a child process managed by Rust.
- Reduce installer size: Core ≤ 500 MB, model pack ≤ 3.5 GB (total ≤ 4 GB bundled; Lite variant 500 MB with on-demand model download).
- Ship incrementally — Rust endpoints come online one at a time, Python backend continues to serve what's not yet ported.

**Non-Goals:**
- Porting Python ML inference to Rust (not in ~8 weeks, probably never — torch ecosystem is Python-native).
- Supporting remote / web deployment (future mobile and hardware products will have their own local Rust backend).
- Rewriting the UI layer — the React codebase in `ui/src/` stays; all HTTP/WebSocket calls keep the same shape.
- Matching Python's code organisation 1:1 — Rust module structure can diverge if it's a cleaner fit.

## 3. Final Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ KALI.exe  (single Tauri binary)                              │
│                                                              │
│  ┌─────────────────┐       ┌────────────────────────────────┐│
│  │ WebView (React) │◄─────►│ Tauri main (Rust, tokio)       ││
│  │ UI unchanged    │ HTTP  │                                ││
│  └─────────────────┘  +WS  │  ┌───────────────────────────┐ ││
│                       :3005│  │ axum server              │ ││
│                            │  │ - HTTP endpoints         │ ││
│                            │  │ - WebSocket /ws          │ ││
│                            │  └──────────┬───────────────┘ ││
│                            │             │                 ││
│                            │  ┌──────────▼───────────────┐ ││
│                            │  │ Domain layer (Rust)      │ ││
│                            │  │ - config, event bus,     │ ││
│                            │  │   skills, builder,       │ ││
│                            │  │   sandbox, llm router    │ ││
│                            │  └──────────┬───────────────┘ ││
│                            │             │                 ││
│                            │  ┌──────────▼───────────────┐ ││
│                            │  │ Python ML worker         │ ││
│                            │  │ (child process)          │ ││
│                            │  │ JSON-over-stdio          │ ││
│                            │  └──────────┬───────────────┘ ││
│                            │             │                 ││
│                            │  ┌──────────▼───────────────┐ ││
│                            │  │ SQLite (rusqlite)        │ ││
│                            │  └──────────────────────────┘ ││
│                            └────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘

Installer: Core (NSIS, ~500 MB) = Tauri binary + Python runtime + UI
           Model pack (~3.5 GB) = F5 weights, vocab, reference audio,
                                  ruaccent ML model, Silero VAD
           First-launch downloader shows progress, cloud TTS fallback
           meanwhile for out-of-box working voice.
```

## 4. Crate Choices

| Need | Crate | Why |
|------|-------|-----|
| HTTP + WS server | `axum` 0.7 | tokio-native, composable middleware, de-facto Rust standard |
| Async runtime | `tokio` 1.x | required by axum; multi-threaded scheduler for ML IO |
| JSON (de)ser | `serde` + `serde_json` | already in Cargo.toml |
| SQLite | `rusqlite` 0.32 | lightweight, synchronous (OK for our scale — small local DB) |
| Schema + migration | `rusqlite_migration` 2.x | versioned migrations, simple |
| HTTP client (for catalog fetch) | `reqwest` 0.12 | tokio-native, tls via rustls |
| Config YAML | `serde_yaml` | matches `config/kali.yaml` |
| Error handling | `anyhow` + `thiserror` | anyhow in handlers, thiserror for domain error types |
| Logging | `tracing` + `tracing-subscriber` + `tracing-appender` | structured, async-aware, rotating file appender |
| Python IPC | `tokio::process::Command` + hand-rolled JSON framing | no crate — simple line-delimited JSON over stdio |
| Audio playback (short clips) | `rodio` | for local jarvis_sounds WAVs without round-trip to Python |
| Time / cron | `chrono` + `tokio-cron-scheduler` | scheduler for morning/evening jobs |
| CORS | `tower-http` (CorsLayer) | standard axum middleware |
| UUID | `uuid` | session ids, event ids |

Total direct deps: ~18. All well-maintained, all have > 1M downloads / month.

## 5. Module Map (Python → Rust)

Rust modules live under `src-tauri/src/backend/`. Existing `src-tauri/src/lib.rs` (Tauri app entry) grows a `mod backend;` declaration and a `backend::start(app_handle)` call in `setup()`.

| Python source | Rust target | Notes |
|---|---|---|
| `kernel/main.py` | `backend/http.rs` + `backend/ws.rs` | HTTP routes + WebSocket handler split |
| `kernel/event_bus.py` | `backend/event_bus.rs` | `tokio::sync::broadcast` channel |
| `kernel/config_manager.py` | `backend/config.rs` | serde_yaml + file watcher |
| `kernel/models.py` | `backend/models.rs` | serde structs mirroring existing Pydantic shapes |
| `kernel/db/*.py` | `backend/db/mod.rs` | rusqlite + migrations |
| `kernel/llm_router.py` | `backend/llm/mod.rs` | reqwest clients per provider |
| `kernel/skills/catalog.py` | `backend/skills/catalog.rs` | reqwest + deserialisation |
| `kernel/skills/installer.py` | `backend/skills/installer.rs` | std::fs + serde_yaml |
| `kernel/sandbox/*.py` | `backend/sandbox/mod.rs` | enforcer + audit sink |
| `kernel/builder/*.py` | `backend/builder/mod.rs` | session store + flow orchestrator |
| `kernel/voice/pipeline.py` | `backend/voice/pipeline.rs` | state machine in Rust; individual ML calls delegate to Python |
| `kernel/voice/recorder.py`, `tts_router.py`, `jarvis_sounds.py` | `backend/voice/{recorder,tts_router,sounds}.rs` | Rust-side audio IO |
| `kernel/voice/tts_engine_f5.py` | **stays in Python**, called via bridge | ML path |
| `kernel/voice/tts_engine_elevenlabs.py` | **stays in Python**, called via bridge | ML/cloud path |
| `kernel/voice/stt.py` | **stays in Python**, called via bridge | ML path |
| `kernel/voice/vad.py` | **stays in Python**, called via bridge | ML path |
| `kernel/voice/wake_word.py` | **stays in Python**, called via bridge | ML path |
| `kernel/voice/text_preprocessor.py` | **stays in Python**, called via bridge | ruaccent ML |
| `kernel/entry.py` | deleted (replaced by Tauri main) | — |

## 6. HTTP + WebSocket Contract (preserved verbatim)

Every endpoint the UI currently consumes (see `ui/src/api/client.ts`) must work identically after migration. Same URL, same method, same request body, same response shape. Rust implementations must match by integration test (see §10).

Initial endpoint set to port (by priority):
- `GET /health` (Phase 0 — see companion plan)
- `GET /config`
- `POST /voice/status`, `POST /voice/start`, `POST /voice/stop`
- WebSocket `/ws` (events: `voice.state`, `voice.pipeline`, `voice.transcript`, `agent.response`, `dashboard.update`, `error`)
- `GET /skills`, `POST /skills/install`, etc.
- `POST /builder/start|answer|deploy|cancel`
- `POST /tts` (proxies to Python ML)

Plus any others found in `ui/src/api/*.ts` during Phase 0 audit.

## 7. Python ML Bridge Protocol

**Transport:** one persistent child process per ML concern (TTS, STT, VAD/wake, preprocessor) spawned by Rust on backend startup. Communication via line-delimited JSON on stdin / stdout.

```
Rust → Python (on stdin): {"id":"uuid","op":"tts_speak","args":{"text":"..."}}\n
Python → Rust (on stdout): {"id":"uuid","result":{"audio":"base64..."}}\n
                        OR {"id":"uuid","error":{"type":"ModelError","message":"..."}}\n
```

Python side is a thin script (~150 lines each) under `kernel/workers/` that imports the relevant module and dispatches. Rust side is a generic `BridgeWorker` that owns the child process, a correlation map `id → oneshot::Sender`, a reader task, and a writer task.

**Lifecycle:** backend spawns workers in `setup()`. Workers auto-restart on crash (max 3 attempts within 60s, then hard fail). Health check every 30s via `{"op":"ping"}`.

**Error modes:** worker crash → Rust returns 503; worker hang (> 30s) → cancel, return 504; malformed JSON → log + 500.

## 8. Error Handling Convention

- **Domain errors:** `thiserror::Error` enums per module (`VoiceError`, `BuilderError`, `SkillsError`, etc.).
- **Handler errors:** `anyhow::Result<T>` unwrapped to `axum::Response` via a central `AppError` type implementing `IntoResponse`.
- **No unwraps in async code paths** except tests and `main.rs` startup.
- **Error response shape** matches current Python: `{"error": {"code": "...", "message": "...", "details": {...}}}` with HTTP status 400/404/500 as appropriate.

## 9. Async Model & Logging

- Single `tokio::runtime::Builder::new_multi_thread()` built in `backend::start`, owned by Tauri.
- No blocking in handlers — all IO is `.await`. CPU-bound work (e.g. SQLite statements) wrapped in `tokio::task::spawn_blocking`.
- `tracing-subscriber` with `EnvFilter` (RUST_LOG env var, default `kali=info`) + rotating file appender to `%APPDATA%/KALI/logs/kali-backend.log` (matches current Python behaviour).
- `tracing::instrument` on every handler for request-level spans; trace IDs flow through events and logs.

## 10. Testing Strategy

- **Unit:** per Rust module, covering pure logic (serialisation, state transitions, scheduling math). Target: 80% branch coverage of domain layer.
- **Integration (in-process):** spawn axum on ephemeral port, hit endpoints with reqwest. Covers: HTTP contract, WebSocket handshake + event flow, error paths.
- **Contract:** for each endpoint ported from Python, a golden-file test captures the Python response shape once; Rust must produce an identical JSON shape. Run against a live Python backend in CI during migration, drop after Python backend retires.
- **Python bridge:** fake ML worker (a stub Python script that echoes request as response) used in tests to exercise the `BridgeWorker` protocol without real models.
- **End-to-end:** existing UI test harness (once Chunk 5 Plan 2 resumes) verifies UI works against Rust backend via Tauri in dev mode.

## 11. Distribution & Packaging

**Core installer (NSIS or Tauri MSI, target ~500 MB):**
- Tauri binary (includes Rust backend + React UI)
- Python 3.12 embed + Python ML worker scripts (`kernel/workers/*.py`) + dependencies (`uv`-locked subset for ML only, no FastAPI / server deps)
- SQLite binary (statically linked via rusqlite)
- `jarvis_sounds/` small WAV clips

**Model pack (downloaded on first launch, ~3.5 GB):**
- F5-TTS checkpoint + vocab + reference audio
- Silero VAD + Whisper base + OpenWakeWord models
- ruaccent ML model
- Saved to `%APPDATA%/KALI/models/`

**First-launch flow:**
1. Tauri opens, React UI boots, shows "Preparing Jarvis" onboarding.
2. Rust backend starts, detects missing model pack.
3. UI asks user to pick: "Full local (3.5 GB download now)" or "Cloud voice only" (zero download, ElevenLabs for voice).
4. If chosen "Full local" → background download with progress bar in UI.
5. Meanwhile user can use chat + cloud voice immediately.
6. When local models arrive → Jarvis announces "голосовой режим готов" and switches automatically.

**Premium installer:** one-shot 4 GB with model pack bundled. Distributed via existing InnoSetup DiskSpanning path.

## 12. Migration Phases

Each phase = one approved implementation plan = 3-10 days of work = one or more atomic commits. Phases are independently shippable — Python backend continues to serve whatever's not yet ported, Rust serves what is.

- **Phase 0 — Scaffolding + `/health`**: Rust axum inside Tauri, first endpoint. Proves the integration path. Plan: `docs/superpowers/plans/2026-04-25-rust-migration-phase-0.md`.
- **Phase 1 — Stateless endpoints**: `/config`, `/version`, `/voice/status`. Read-only, no side effects. ~1 week.
- **Phase 2 — WebSocket + event bus**: Rust event bus, Rust WS, Python publishes into it via bridge. UI keeps working unchanged. ~1 week.
- **Phase 3 — Voice pipeline orchestration**: state machine in Rust, ML calls via bridge. Retires Python `kernel/voice/pipeline.py`. **After this phase, resume Plan 2 Chunk 5.** ~2 weeks.
- **Phase 4 — Skills catalog + installer**: HTTP catalog + SKILL.md installer in Rust. ~1 week.
- **Phase 5 — Builder flow**: BuilderFlow + SessionStore in Rust. ~5 days.
- **Phase 6 — LLM router + sandbox**: provider selection, enforcement, audit. ~1 week.
- **Phase 7 — DB + scheduler + cleanup**: rusqlite migrations, tokio-cron-scheduler, retire last Python orchestration endpoints. ~1 week.
- **Phase 8 — Python retirement**: delete `kernel/main.py`, `kernel/entry.py`, FastAPI deps. ML workers remain. Update installer scripts.

Total: 8-10 weeks solo, assuming no major blockers. Phases 1-8 plans will be written before their execution starts — not all upfront, to keep plans fresh against reality.

## 13. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bridge latency hurts voice responsiveness | Med | Med | Measure Phase 3 end-to-end; subprocess stdio adds ~1-5 ms, negligible vs F5 inference (500+ ms). Long-running call budgets in the protocol. |
| Python worker crashes under production load | Med | High | Auto-restart policy; supervisor log on repeated failure; fallback to cloud TTS for user-visible continuity. |
| Rust SQLite schema drift vs Python | Low | Med | Read current Python schema, write rusqlite_migration matching it exactly. Schema changes only in a dedicated phase. |
| WebView CSP breaks when CORS changes | Low | Med | `tauri.conf.json` CSP already allows `localhost:3005` — unchanged. |
| Rust HTTP response shapes drift from Python | Med | High | Golden-file contract tests (see §10). |
| Multi-provider LLM router complexity | Med | Med | Single-provider MVP (OpenAI) in Phase 6; other providers follow. |
| Installer migration breaks for existing users | Low | High | Preserve `%APPDATA%/KALI/` layout; new backend reads existing DB / config. Separate migration step only if schema actually changes. |
| Solo-dev timeline overrun | High | Med | Phases are independently shippable. Can stop after Phase 3 (voice + events Rust) and still have 80% of the product value. |

## 14. Success Criteria

- `cargo test` green on every commit.
- HTTP/WS contract tests pass against Rust endpoints (100% of ported endpoints).
- Tauri dev mode runs with Rust backend, UI fully functional, no regressions.
- Installer ≤ 4 GB Premium / ≤ 500 MB Lite.
- Retire `kernel/main.py` + `kernel/entry.py` by end of Phase 8.
- Memory: `project_rust_migration.md` marked "DONE" when Phase 8 closes.
