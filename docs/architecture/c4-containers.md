# KALI — Container Diagram (C4 Level 2)

**Audience:** Technical — engineers, PMs with technical fluency, architects reviewing design.
**Purpose:** Show major deployable/runnable units of KALI and how they fit together.

## Diagram

> **Render:** [c4-containers.puml](c4-containers.puml) — paste at [plantuml.com/plantuml](https://www.plantuml.com/plantuml).

```plantuml
@startuml c4-containers
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Container.puml

title Container Diagram — KALI Desktop

Person(user, "User", "Speaks or types ideas, listens to JARVIS voice.")

System_Boundary(kali, "KALI Desktop") {
    Container(shell, "Tauri Shell", "Rust + React 19 + WebView2", "Desktop window. Renders chat, Agent Store, Activity, Builder panels.")
    Container(backend, "FastAPI Backend", "Python 3.12 + uvicorn (port 3005)", "Kernel: voice pipeline, agent runtime, skills, sandbox, builder.")
    ContainerDb(db, "Local State DB", "SQLite (aiosqlite)", "User config, audit log, conversation history, agent deployments.")
    Container(f5, "F5-TTS Engine", "PyTorch + CUDA (in-process)", "Local voice synth. JARVIS clone via ref-audio. RTX 20-series+ required.")
    Container(stt, "Whisper STT + VAD", "faster-whisper + Silero VAD + OpenWakeWord", "Wake word detection, voice-activity segmentation, transcription.")
    Container(sounds, "JARVIS Sound Pack", "MP3 clips", "Pre-recorded short phrases (greetings, confirms). Fast-path, no TTS round-trip.")
    ContainerDb(agents, "Agents Directory", "Filesystem", "Skill/agent YAMLs + Python. Installed from catalog or generated.")
    ContainerDb(models, "Models Directory", "Filesystem + gitignored", "F5 checkpoint 1.3 GB, vocab, reference WAVs, FFmpeg DLLs.")
}

System_Ext(claude, "Claude API", "Anthropic")
System_Ext(openai, "OpenAI API", "GPT-4o")
System_Ext(elevenlabs, "ElevenLabs", "Cloud TTS")
System_Ext(github, "GitHub", "SKILL.md registries")
System_Ext(neuraldeep, "NeuralDeep", "RU aggregator")
System_Ext(google, "Google APIs", "Calendar / Gmail")
System_Ext(telegram, "Telegram Bot", "Notifications")

Rel(user, shell, "Clicks, types, speaks into mic")
Rel(shell, backend, "API calls + WebSocket events", "HTTP/JSON, WS (port 3005)")

Rel(backend, db, "CRUD state", "aiosqlite")
Rel(backend, f5, "Synthesise speech (GPU path)", "In-process call")
Rel(backend, stt, "Transcribe mic audio", "In-process call")
Rel(backend, sounds, "Play pre-recorded clip", "File read + sounddevice")
Rel(backend, agents, "Load skill YAMLs + agent.py", "File read/write")
Rel(backend, models, "Read voice model weights", "File read")

Rel(backend, claude, "LLM requests (intent, generation, chat)", "HTTPS / anthropic SDK")
Rel(backend, openai, "LLM requests (alternative)", "HTTPS / openai SDK")
Rel(backend, elevenlabs, "Cloud TTS (fallback)", "HTTPS / elevenlabs SDK")
Rel(backend, github, "Fetch SKILL.md + trees", "HTTPS / GitHub REST")
Rel(backend, neuraldeep, "Fetch aggregated RU catalog", "HTTPS / JSON")
Rel(backend, google, "Calendar/Gmail per user", "HTTPS / OAuth2")
Rel(backend, telegram, "Send notifications", "HTTPS / Bot API")

SHOW_LEGEND()

@enduml
```

## Container Purposes

| Container | Tech | Why it's separate |
|---|---|---|
| **Tauri Shell** (`kali-desktop.exe`) | Rust wrapper + React 19 + WebView2 | User-facing UI; must be OS-native for polish. Embeds Edge WebView2, not Chromium — smaller installer. |
| **FastAPI Backend** (`kali-backend.exe`) | Python 3.12 + uvicorn + PyInstaller `--onedir` | All heavy logic: voice, agents, sandbox. Separate process so Tauri crashes don't kill agents and vice versa. Connected via localhost:3005 + WebSocket. |
| **Local State DB** | SQLite via `aiosqlite` | Durability for user data — agents, audit log, settings. Single-file, no server, user owns their data. Lives in `%APPDATA%/KALI/kali.db`. |
| **F5-TTS Engine** | PyTorch 2.11 + CUDA 12.8 | Voice model. In-process (not separate service) to avoid fork-bomb risk with PyInstaller `--onefile`. Loads ~1.3 GB checkpoint lazily on first TTS call. |
| **Whisper STT + VAD** | faster-whisper + Silero VAD (torch.hub) + OpenWakeWord ONNX | Audio input pipeline. Runs continuously when voice mode active. CPU-only; cheap. |
| **JARVIS Sound Pack** | MP3 clips | Fast path for common phrases ("ок", "готово", greetings). Bypasses TTS entirely — sub-100ms response. |
| **Agents Directory** | `agents/*/` filesystem | Installed + user-authored agents. Hot-reloadable via `plugin_registry` discovery. Dual format: legacy `manifest.yaml` + new `SKILL.md`. |
| **Models Directory** | `models/*` (gitignored) | Binary weights — too big for git, downloaded/bundled at install. Includes FFmpeg shared DLLs for torchcodec. |

## Key Architectural Decisions

### In-process agents, not subprocess
Early design had each agent as a subprocess via JSON-RPC. This broke PyInstaller `--onefile` — `sys.executable` points at `kali-backend.exe` and each subprocess spawned another full backend copy (fork bomb). Solution: `kernel/agent_runtime/protocols/inprocess.py` — agents loaded as Python modules, not processes.

### Tauri over Electron
Tauri ships a ~200 MB smaller installer (uses OS WebView2 instead of embedded Chromium) and feels more native. Cost: Rust in the stack for anyone touching shell plumbing. Acceptable — backend is where the action is.

### Two installer variants (out of scope for this diagram)
- **Lite** (~100 MB): ElevenLabs cloud voice, no GPU deps. Telegram-shareable.
- **Premium** (~4-5 GB): F5-TTS local + CUDA torch. Google Drive / InnoSetup multi-slice.

## Deployment Model

**Desktop only (today).** Single-user, single-machine. All state local. No cloud sync, no auth, no telemetry. This is intentional — privacy-first positioning, avoid infrastructure cost until validated.

**Next:** Mobile (React Native or Flutter) will reuse the same HTTP API contract as Tauri. A user's desktop backend could in theory serve their phone over LAN, but cloud sync (user account + encrypted state) is the likely path.

## Not Shown

- **Scheduler** / **Cron** — lives inside backend as a module; not deployable separately. Shown in component diagram.
- **Event bus** — in-process pub/sub inside backend, not a MQ.
- **Build artifacts** (PyInstaller, Tauri bundles) — build concern, not runtime.
