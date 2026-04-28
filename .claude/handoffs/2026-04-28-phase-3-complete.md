---
handoff_date: 2026-04-28
project: KALI — Personal AI OS
branch: main
latest_commit: a92770c
version: 0.2.0-beta
continues_from: 2026-04-27-phase-3-4of8.md
session_commits: 4
---

# KALI Handoff — 2026-04-28 — Phase 3 SHIPPED 8/8, Tier 1 effective 6/6

## Current State Summary

One long session that closed the back half of Phase 3 — Chunks 5, 6, 7, 8 — in four atomic commits. The Rust backend now contains the full voice pipeline: cpal recorder + rodio playback + anti-echo MuteFlag (Chunk 6), OpenWakeWord via Python sidecar (Chunk 5, path B), a 7-state PipelineMachine + concrete runner with dedicated PlaybackThread (Chunk 7), and native `/voice/start`, `/voice/stop`, `/voice/status` HTTP routes with an axum Extension dispatch that flips between native and Python-proxy mode based on the `voice.engine` config flag (Chunk 8).

Default ships `engine: python`. The flip to `engine: rust` is **deliberately split into a separate one-line commit** that lands ONLY after Vasily's live rehearsal on real hardware. That gate keeps the rollback granularity surgical — if the rehearsal exposes a bug, we revert the flip without touching the routing code.

**Tier 1 = effective 6/6 closed code-wise.** Item #6 (Feedback channel) was dropped 2026-04-25 per the app-minimalism rule; #7 (Phase 3) is now done. After the cutover commit + premium installer rebuild + friend-test distribution, Tier 1 is fully cashed in.

**Current active work:** nothing in-progress at commit boundary. All 4 commits atomic, all default tests green, all gated suites compile clean.

## Important Context

### Working rule set (unchanged)
- **"Предложи → обсудим → сделаем"** — never silently ship non-trivial features.
- **Documentation commits** land without explicit approval.
- **Feature/refactor commits** wait for explicit "go" / "давай" / "ок".
- **No PR review** — solo dev, direct-to-main.

### New rule established this session

- **Research best practices before nuance decisions** (`feedback_research_before_nuance.md`): on delegated nuance choices (library versions, naming, file layout), do a quick best-practices assessment FIRST, document the conclusion, then proceed without re-confirming. Vasily explicitly granted autonomy on those *if* the homework is done first.

### Reinforced this session

- **Path B (Python sidecar) is the right call when Rust-native parity is risky.** STT (Chunk 3) was the precedent; wake-word (Chunk 5) followed the same pattern after planning revealed openwakeword is a 3-ONNX chain (melspectrogram → embedding → keyword), not a single model. Re-implementing the chain in Rust with mel-spec parity below 5% RMS would have been a 12-18h gamble; path B was 3-5h and uses upstream openwakeword as-is.
- **Pure state machine + runner separation pays.** `state.rs` (data + step()) gets full TDD coverage (17 unit tests cover the transition matrix); `pipeline.rs` (concrete engine wiring + async select-loop) is integration-only by design. Reusable for any future state graph (agent builder flow, etc.).
- **Engine cutover is a separate commit.** Rollback granularity matters — bundling the flip with the routing PR would force any rollback to also undo the routing.

### Environment (carry-forward)

- OS: Windows 11, Python 3.12 via uv, shell = bash via Claude (forward slashes), PowerShell/cmd for user.
- GPU: RTX 5070 Laptop (Blackwell sm_120) — torch cu128.
- Repo: `github.com/VasilyKolbenev/kali-ai-os` on `main`.
- Tauri 2 shell, React 19 + TS + Tailwind 4, Vitest, Cargo. Rust backend on :3006 alongside Python kernel on :3005.
- New crates this session: `cpal = "0.17"`, `rodio = "0.22"`. ndarray + ort versions unchanged from Chunk 4.

## Key Architecture Decisions (new this session)

| Decision | Rationale | Where locked |
|---|---|---|
| **Wake-word stays in Python sidecar (Chunk 5 path B)** | openwakeword is a 3-ONNX chain bundled inside the upstream package. Re-implementing mel/embedding preprocessing in Rust risks <5% RMS divergence → false negatives. IPC overhead at the 80ms wake cadence (~5 ms per call) is invisible against F5 inference (500 ms+) on the same bridge. | `kernel/workers/tts_worker.py::_handle_wake_detect` + `src-tauri/src/backend/voice/wake_word.rs::WakeWordClient` |
| **Wake-detect needs an in-flight gate** | Recorder cadence (33 chunks/sec at 30 ms) would queue 33 concurrent bridge calls if `wake.detect` were spawned per chunk. `Arc<AtomicBool>` swap-true at spawn, store-false at completion → effective polling rate ~10 Hz, matches openwakeword's design point. | `src-tauri/src/backend/voice/pipeline.rs::PipelineRunner::handle_action` |
| **Pipeline = pure state machine + runner** | Splits orchestration into `state.rs` (data + step() pure function — fully unit-testable) and `pipeline.rs` (runner with concrete engines). Avoids needing async traits + mocks for the engines. 17 unit tests cover the transition matrix; runner has compile-only verification + Vasily's manual rehearsal. | `src-tauri/src/backend/voice/state.rs` (470 LoC) + `pipeline.rs` (370 LoC) |
| **cpal `Stream` is `!Send` → dedicated std::thread + std::mpsc → tokio::oneshot bridge** | Reused for both Recorder (input) and PlaybackThread (output). Pattern: spawn thread, requests via `std::sync::mpsc::SyncSender`, completion via `tokio::sync::oneshot`. Runner stays fully `Send` and tokio-compatible. | `recorder.rs::Recorder::start` + `pipeline.rs::PlaybackThread::spawn` |
| **VAD reframing: 480 → 512 samples** | Recorder gives 480-sample chunks (30 ms); Silero VAD requires strict 512 (32 ms). Runner buffers and drains in 512-sample groups. Don't change recorder chunk size — 30 ms is the standard for VAD/wake feeders downstream. | `pipeline.rs::PipelineRunner::handle_action` `FeedVad` arm |
| **Pipeline as axum `Extension`, not `State`** | Optional handle (`Option<Arc<Pipeline>>`) flows through router via Extension layer. Voice handlers extract via `Extension(pipeline): Extension<PipelineHandle>` and branch on Some/None. Existing `State<Arc<EventBus>>` extractors on `/health`, `/ws` etc. untouched. Backwards compat via `router_with_bus(bus)` → forwards `None` pipeline. | `src-tauri/src/backend/http.rs::router_with_bus_and_pipeline` |
| **Engine cutover deferred to a separate commit** | Default ships `engine: python`. Flip to `rust` is a one-liner gated on live rehearsal. Rollback granularity > convenience. | TBD — separate commit after rehearsal |
| **`audio-tests` Cargo feature** | Sibling to `ml-tests`. Gates anything that opens real audio devices (mic / speaker). Default `cargo test` must never touch the user's mic — privacy + CI compatibility. Plan-conformant runtime-skip on recorder was switched to feature gate. | `src-tauri/Cargo.toml` `[features] audio-tests = []` |
| **VoiceConfig.engine: String (Rust) / Literal (Python)** | Default `"python"`. `#[serde(default)]` keeps old kali.yaml files loading. Python-side: `Literal["python", "rust"] = "python"` in `kernel/models.py::VoiceConfig`. | `src-tauri/src/backend/config.rs` + `kernel/models.py` |

## Confirmed Roadmap v2.7 (from `memory/project_roadmap.md`)

### Tier 1 — Non-tech distribution unblock
| # | Item | Status |
|---|---|---|
| 1-5 | Plan 2 Ch5, Rust Phase 1, Onboarding, Settings UI 5/5, Rust Phase 2 4/4 | ✅ |
| 6 | Feedback channel | ❌ DROPPED 2026-04-25 (manual collection) |
| 7 | Rust Phase 3 voice pipeline | ✅ **8/8 SHIPPED 2026-04-28** |

Effective Tier 1: **6/6 closed code-wise.** Awaiting cutover + installer rebuild + friend tests for the practical close.

### Phase 3 chunk-level status (FINAL)

| Chunk | Status | Commit |
|---|---|---|
| 1 — JSON-stdio bridge primitive + Python worker shell | ✅ | `263a958` |
| 2 — TTS over bridge | ✅ | `87e5946` |
| 3 — STT path B (faster-whisper in worker) | ✅ | `35a9e78` |
| 4 — Silero VAD via ort + ONNX | ✅ | `ee813d6` |
| 5 — OpenWakeWord path B (Python sidecar) | ✅ | `6907d0d` |
| 6 — cpal recorder + rodio playback + anti-echo mute | ✅ | `c704bf1` |
| 7 — Pipeline state machine + anti-echo runner | ✅ | `3d43caa` |
| 8 — Native `/voice/*` HTTP routes + engine flag | ✅ | `a92770c` |

## Pending Work

### Immediate next-session sequence (highest leverage)

**1. Live rehearsal on dev machine (~30-60 min, manual).** Goal: prove the Rust path works end-to-end before flipping the default. Steps:

```bash
# 1. Edit config/kali.yaml — set voice.engine: rust temporarily for rehearsal
# 2. Start Python backend on :3005 (it serves /chat + agents + skills)
.venv/Scripts/python.exe -m kernel.main

# 3. Start Rust backend on :3006 (will spawn ML bridge + Pipeline since engine=rust)
cargo run --bin backend_dev --manifest-path src-tauri/Cargo.toml

# 4. (optional) Audio smoke first — both gated tests, opt-in:
cargo test --features audio-tests --test voice_recorder      # records 100ms from your mic
cargo test --features audio-tests --test voice_playback      # plays 1s 440Hz tone
cargo test --features ml-tests --test voice_wake_word        # silence + reset

# 5. Manually exercise: through the Tauri app (or curl to :3006):
curl -X POST http://127.0.0.1:3006/voice/start
# Say "hey jarvis, какая погода сейчас"
# Listen for the TTS reply
curl -X POST http://127.0.0.1:3006/voice/stop

# 6. If green → revert kali.yaml, then make the cutover commit (next item).
# 7. If problems — debug Rust Pipeline runner; rollback the kali.yaml edit.
```

**2. Cutover one-liner commit (~5 min, after rehearsal passes).**

```bash
# Edit config/kali.yaml — flip voice.engine from "python" to "rust".
# Document the rehearsal date in the file as a comment if you want.

git add config/kali.yaml
git commit -m "feat(voice): flip default voice.engine to rust (Phase 3 cutover)

Verified live on dev machine 2026-MM-DD: wake -> STT -> /chat ->
TTS -> playback round trip works in <SOME>s. The Python pipeline
path remains in the codebase as engine=python fallback for at
least one release cycle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**3. Premium installer rebuild (~30 min).** Bundle now ships with the Rust pipeline as authoritative. Follow `docs/architecture/` if it has the rebuild dance; otherwise:

```bash
uv run --with pyinstaller python scripts/build_backend_premium.py
xcopy /E /I /Y dist_premium\kali-backend dist_premium\premium_stage\kali-backend
scripts\build_installer_premium.bat
```

After rebuild: `dist_premium/installer/` should hold `KALI-Setup-0.2.X-...iso` (or split parts) ready for friends.

**4. Friend-test rollout (1-3 friends).** Privacy-aware feedback collection per `feedback_app_minimalism.md` — Vasily collects manually, no in-app channel. Watch for:
- Install completes without `.env` editing.
- First wake → first reply in < 3 minutes (Tier 1 success metric).
- "Hey jarvis" recognition rate on Russian-speaker pronunciation. If poor → consider custom keyword model training (Phase 4+).

### Critical — read before action

```bash
git log --oneline -7
# top 4 lines should match (newest first):
#   a92770c feat(voice): native /voice/* routes + engine feature flag (Phase 3 Chunk 8)
#   3d43caa feat(voice): pipeline state machine + anti-echo runner (Phase 3 Chunk 7)
#   6907d0d feat(voice): wake word in Python sidecar via openwakeword (Phase 3 Chunk 5, path B)
#   c704bf1 feat(voice): cpal recorder + rodio playback + anti-echo mute (Phase 3 Chunk 6)
#   fc8185d docs(handoff): 2026-04-27 — Phase 3 at 4/8, Tier 1 effective 5/6
#   ee813d6 feat(voice): Silero VAD via ort + ONNX (Phase 3 Chunk 4)
#   35a9e78 feat(voice): STT in Python sidecar via faster-whisper (Phase 3 Chunk 3, path B)

cargo test --manifest-path src-tauri/Cargo.toml         # default suite must be 62 passing
cargo check --manifest-path src-tauri/Cargo.toml --features ml-tests --tests   # exit 0
cargo check --manifest-path src-tauri/Cargo.toml --features audio-tests --tests # exit 0
cd ui && pnpm test                                                              # 61 passed, 1 skipped
cd ui && npx tsc --noEmit                                                       # exit 0
```

If any fails, **stop and investigate** before writing new code.

### Known gotchas (carry-forward — read before touching the voice pipeline)

All in `memory/feedback_ml_build_friction.md` + `memory/project_rust_migration.md` (operational patterns section). Phase 3 close added these:

1. **OpenWakeWord is a 3-ONNX chain** — `melspectrogram.onnx` → `embedding_model.onnx` → `hey_jarvis_v0.1.onnx`. Bundled inside the upstream Python package. Path A (Rust-native) is parity-risky and deferred to Phase 4+.
2. **cpal 0.17 API delta from 0.16** — `SampleRate` is now a pub type alias for `u32`; `min_sample_rate()` / `max_sample_rate()` return primitive `u32` directly (was tuple struct).
3. **rodio 0.22 redesign** — `OutputStream` gone; use `DeviceSinkBuilder::open_default_sink()` → `MixerDeviceSink` → `mixer()` → `Player::connect_new`. Top-level `rodio::Player` exists; name your own struct differently (we use `Speaker`).
4. **Wake-detect in-flight gate** — without an `Arc<AtomicBool>` at the runner's `FeedWake` action, recorder's 33 chunks/sec would queue 33 concurrent bridge calls per second on a worker that processes them sequentially.
5. **VAD reframing** — recorder's 480-sample chunks (30 ms) need re-framing to Silero's strict 512 (32 ms). Runner has a `vad_buffer` that drains in 512-groups.
6. **Engine cutover discipline** — separate commit, gated on live rehearsal. Don't bundle.
7. **`KALI_PYTHON_BACKEND_URL` is process-wide** — parallel cargo proxy tests race on the env var. Combine related proxy assertions into ONE `#[tokio::test]` function instead of splitting per route.

## Critical Files (created/changed this session)

### Rust backend
- `src-tauri/src/backend/voice/mute.rs` (new, 75 LoC) — `MuteFlag(Arc<AtomicBool>)` + 4 unit tests.
- `src-tauri/src/backend/voice/recorder.rs` (new, 285 LoC) — cpal capture, dedicated std::thread, 8 unit tests on pure helpers.
- `src-tauri/src/backend/voice/playback.rs` (new, 170 LoC) — `Speaker` (rodio MixerDeviceSink + Player) + `MutedGuard` RAII + 6 unit tests.
- `src-tauri/src/backend/voice/wake_word.rs` (new, 110 LoC) — `WakeWordClient` over BridgeWorker, mirrors SttClient. 1 lib unit (b64 round-trip).
- `src-tauri/src/backend/voice/state.rs` (new, ~470 LoC) — pure state machine + 17 unit tests covering full transition matrix.
- `src-tauri/src/backend/voice/pipeline.rs` (new, ~370 LoC) — runner: concrete engines + async select-loop + PlaybackThread + wake-detect in-flight gate.
- `src-tauri/src/backend/voice/mod.rs` — declares the 4 new modules (`mute`, `playback`, `recorder`, `state`, `pipeline`, `wake_word`).
- `src-tauri/src/backend/config.rs` — `VoiceConfig` gains `wake_threshold`, `wake_listen_timeout_secs`, `silence_chunks_to_end`, `min_speech_chunks`, `engine`. All `#[serde(default)]`.
- `src-tauri/src/backend/http.rs` — `voice_start`, `voice_stop` POST handlers + conditional dispatch via `Extension<Option<Arc<Pipeline>>>`. New `router_with_bus_and_pipeline()` constructor.
- `src-tauri/src/backend/proxy.rs` — `proxy_post_json` helper (mirror of `proxy_patch_json`).
- `src-tauri/src/backend/mod.rs` — `serve()` builds Pipeline if `engine=rust`, attaches as Extension; fails loudly on construction errors.
- `src-tauri/Cargo.toml` — added `cpal = "0.17"`, `rodio = "0.22"`, feature `audio-tests`.

### Python sidecar
- `kernel/workers/tts_worker.py` — added `wake_detect` + `wake_reset` ops + `_ensure_wake_word()` lazy load.
- `kernel/main.py` — wraps `VoicePipeline(...)` init in `if config.voice.engine == "python":` so engine=rust leaves Python's `app.state.voice_pipeline = None`.
- `kernel/models.py` — `VoiceConfig` gains `engine: Literal["python", "rust"] = "python"`.

### Frontend
- `ui/src/api/endpoints.ts` — `RUST_ENDPOINTS` gains `POST /voice/start`, `POST /voice/stop`.

### Tests
- `src-tauri/tests/voice_recorder.rs` (new, audio-tests gated) — 100 ms capture smoke.
- `src-tauri/tests/voice_playback.rs` (new, audio-tests gated) — 1 s 440 Hz tone (manual ear check).
- `src-tauri/tests/voice_wake_word.rs` (new, ml-tests gated) — silence non-fire + reset.
- `src-tauri/tests/voice_routes_proxy.rs` (new, default suite) — combined proxy contract test for all three voice routes.

### Memory (private, auto-loaded)
- `memory/MEMORY.md` — index updated.
- `memory/project_roadmap.md` — v2.4 → v2.7 (Phase 3 closed).
- `memory/project_rust_migration.md` — Phase 3 row → 8/8 SHIPPED. Added 9 new operational patterns this session.
- `memory/feedback_research_before_nuance.md` — new (Vasily's autonomy contract on small decisions).

## Test Status

- **UI:** 61 passing, 1 skipped (unchanged across all 4 chunks).
- **Rust default:** **62 passing** (was 25 at start of session, +37 across the four chunks). New default-suite tests added this session:
  - Lib unit (inline `#[cfg(test)]`): mute (4) + recorder helpers (8) + playback helpers (6) + wake_word b64 (1) + state machine transition matrix (17) = 36 lib unit tests.
  - Integration: voice_routes_proxy (1, combined contract for /voice/start, /voice/stop, /voice/status proxy mode).
  - Headline: **62 passing, 0 failed, 0 skipped, 0 ignored**.
- **Rust ml-tests gated:** existing voice_tts (1), voice_stt (1), voice_vad (3 + 1 ignored), plus voice_wake_word (2). Live verified during Chunk 5 dev (17.95 s on dev box).
- **Rust audio-tests gated:** voice_recorder (1), voice_playback (1). NOT live-verified yet — Vasily's manual rehearsal at the close of Phase 3 will run them.
- **Python kernel:** unchanged (`tests/kernel/test_*` not touched this session).

## Common Commands

```bash
# Default test suite (must stay 62 passing)
cargo test --manifest-path src-tauri/Cargo.toml

# Live audio smokes (mic + speakers — opt-in)
cargo test --features audio-tests --test voice_recorder
cargo test --features audio-tests --test voice_playback

# Live ML smokes (wake + STT + TTS via bridge — opt-in)
cargo test --features ml-tests --test voice_wake_word
cargo test --features ml-tests --test voice_stt
cargo test --features ml-tests --test voice_tts
cargo test --features ml-tests --test voice_vad

# Headless Rust backend (no Tauri window) — for live rehearsal
cargo run --bin backend_dev --manifest-path src-tauri/Cargo.toml

# Full Tauri stack
npm --prefix ui run build && cargo run --manifest-path src-tauri/Cargo.toml

# UI suite
cd ui && pnpm test
cd ui && npx tsc --noEmit

# Phase 2 WS smoke (still useful)
.venv/Scripts/python.exe scripts/smoke_phase2_ws.py

# Manual TTS via worker
echo '{"id":"x","op":"tts_speak","args":{"text":"Привет"}}' | \
    .venv/Scripts/python.exe -m kernel.workers.tts_worker 2>/dev/null | \
    head -3

# Manual wake-detect via worker (silence — should return detected=false)
.venv/Scripts/python.exe -c "import json,base64,sys; \
b=base64.b64encode(bytes(32000)).decode(); \
print(json.dumps({'id':'w','op':'wake_detect','args':{'audio_b64':b,'sample_rate':16000,'threshold':0.5}}))" | \
    .venv/Scripts/python.exe -m kernel.workers.tts_worker 2>/dev/null | tail -1

# Premium installer rebuild (after engine=rust cutover)
uv run --with pyinstaller python scripts/build_backend_premium.py
xcopy /E /I /Y dist_premium\kali-backend dist_premium\premium_stage\kali-backend
scripts\build_installer_premium.bat
```

## Immediate Next Steps (for next agent)

1. **Greet user in Russian.** Acknowledge continuity — Phase 3 closed in one massive session (4 chunks, 4 commits).

2. **Verify state before any code:**
   ```bash
   git log --oneline -7              # top MUST be a92770c
   cargo test --manifest-path src-tauri/Cargo.toml      # 62 passed
   cd ui && pnpm test                                    # 61 passed, 1 skipped
   cd ui && npx tsc --noEmit                            # exit 0
   ```
   If any fails — STOP and diagnose.

3. **Ask user about live rehearsal.** The next gate is Vasily running the Rust pipeline against a real mic on his dev machine. He should:
   - Edit `config/kali.yaml` to flip `voice.engine: rust` temporarily.
   - Start Python on :3005 (still needed for `/chat` + agents + skills).
   - Start Rust backend on :3006 (`cargo run --bin backend_dev`).
   - In a Tauri window OR via curl: `POST /voice/start` → speak → confirm round trip.
   - On success: revert kali.yaml, make the cutover commit (template above).
   - On failure: debug, no cutover yet.

4. **Read `memory/feedback_ml_build_friction.md` + `memory/project_rust_migration.md`** before touching any voice code. The operational patterns there (FD redirect, HF_HOME, ndarray pin, ort error trait, decimation aliasing, cpal threading, VAD reframing, wake-detect gating, engine cutover discipline) are all costly to rediscover.

5. **Don't bundle commits.** Cutover stays separate. Premium rebuild is its own commit. Friend-test feedback collection is manual (no in-app channel — see `memory/feedback_app_minimalism.md`).

## Pending rebuild / manual verification (not blocking)

- **Live audio rehearsal** — see Immediate Next Steps #3. Required before cutover.
- **Premium installer rebuild after cutover** — current 3.13 GB installer (rebuilt 2026-04-27) embeds the Python-pipeline backend; once `engine=rust` is default, the bundle shape changes (still ships Python for `/chat` + agents but `kernel/voice/*.py` modules become dead weight that can stay in-place for one release cycle).
- **Custom keyword model training** if "hey_jarvis_v0.1" has poor recall on Russian-speaker pronunciation of "джарвис". Phase 4+ task.

## Communication Style for User

(unchanged from last handoff — Russian conversation, English code, "Предложи → обсудим → сделаем", honest self-assessment, no emoji flood, ask before long-running builds, plan-before-code commitment, research-before-nuance autonomy on small decisions.)

## GitHub State

- Remote: `github.com/VasilyKolbenev/kali-ai-os.git`
- Branch: `main`
- Latest commit: `a92770c`
- Tag: `v0.2.0-beta` (unchanged — bump when Phase 3 cutover lands and Premium rebuilds).
- No open PRs — solo dev.
- Working tree clean except `.claude/settings.local.json` (local, ignored), `out/` (gitignored A/B voice output), `models/silero_vad.onnx` + `models/ggml-base.bin` (downloaded earlier, gitignored along with the F5 checkpoint).

## User's Strategic Vision (unchanged North Star)

> KALI = voice-first AI OS that lets non-tech people (строитель/врач/офисник 30+) create AI agents by speaking. Distribution via UGC reels in TikTok/Reels. Desktop (Studio) → Mobile (Consumer) → Hardware device (CLIK + Starlink). **Rust backend + polished non-tech onboarding = differentiation vs OpenClaw (Python, developer-targeted).**

Monetization unchanged: Free + Pro $9.99/mo today, KALI Device $399 + $9.99/mo Q4 2026, seed criteria K-factor > 1 + 50+ paying + D30 retention > 30%.

---

*Handoff created 2026-04-28 after a 4-commit session that drove Phase 3 from 4/8 to 8/8 in one sitting. Tier 1 effective 6/6 closed code-wise; the practical close needs a live rehearsal + cutover commit + installer rebuild + friend tests. Valid until the next significant commit batch. When in doubt, trust `git log` + this doc + `memory/*.md`.*
