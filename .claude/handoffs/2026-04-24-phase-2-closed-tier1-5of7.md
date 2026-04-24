---
handoff_date: 2026-04-24 (late evening)
project: KALI — Personal AI OS
branch: main
latest_commit: 7e0a36b
version: 0.2.0-beta
continues_from: 2026-04-24-tier-1-massive-progress.md
session_commits: 9
---

# KALI Handoff — 2026-04-24 late — Phase 2 closed, Tier 1 at 5/7

## Current State Summary

Second extraordinary session of 2026-04-24 — picking up from the 38-commit morning handoff (`a67d72f`) and adding another 9 commits. Closed **two major Tier 1 items** (Settings UI + Rust Phase 2) and wrote the Phase 2 plan from scratch in one sitting.

1. **Settings UI — FULLY CLOSED (5/5 chunks).** Chunk 2 (design-token polish across Settings.tsx + LlmSettings + AdvancedSettings) and Chunk 3 (Voice section via `PATCH /config` with RFC 7396 merge-patch, Rust proxy forwarding, atomic YAML write + `.bak` backup) shipped this session. Non-tech users can now change wake word / auto-start / mode / LLM keys / language without touching `.env`.

2. **Rust Phase 2 — FULLY CLOSED (4/4 chunks).** WebSocket `/ws` on :3006 fronted by `tokio::sync::broadcast` bus; Python `RustEventBridge` posts relayed events to `/_internal/events`; UI points at `rustWsUrl` with legacy `wsUrl` kept for rollback; `/health` exposes `ws_subscribers` gauge and every WS connection is traced with a per-connection `sub_id`. Full plan lives at `docs/superpowers/plans/2026-05-09-rust-migration-phase-2.md` (1046 lines).

3. **Tier 1 jumped from 3/7 to 5/7 in one evening.** #6 Feedback channel and #7 Rust Phase 3 voice pipeline are now UNBLOCKED — their gating dep (Phase 2) is done.

**Current active work:** nothing in-progress at commit boundary. All 9 commits atomic, all test suites green (cargo 17/17, pytest 40/40 in affected files + 6 new `test_rust_bridge` cases, pnpm 61 passed + 1 skipped, `tsc --noEmit` clean).

## Important Context

### Working rule set (unchanged)
- **"Предложи → обсудим → сделаем"** — never silently ship non-trivial features.
- **Documentation commits** land without explicit approval.
- **Feature/refactor commits** wait for explicit "go" / "давай" / "ок".
- **No PR review** — solo dev, direct-to-main.

### Environment (carry-forward)
- OS: Windows 11, Python 3.12 via uv, shell = bash via Claude (forward slashes), PowerShell/cmd for user.
- GPU: RTX 5070 Laptop (Blackwell sm_120) — torch cu128.
- Repo: `github.com/VasilyKolbenev/kali-ai-os` on `main`.
- Tauri 2 shell, React 19 + TS + Tailwind 4, Vitest + @testing-library, vitest test timeout = 15s.
- Backend runtime: Python on `:3005` (full stack), Rust on `:3006` (migrated endpoints + WS + ingestion).

### New rule established this session
- **"For dispatcher-level routing, always pick prod-correct over pragmatic."** User explicitly chose γ (method-aware `PATCH /config` through Rust proxy with JSON merge-patch) over α (`POST /config/voice` scope-scoped endpoint) because quality beats speed. Rule: when faced with "simpler but accumulating debt" vs "larger but canonical" in foundational wiring, pick canonical. Premature simplicity costs more later.

## Key Architecture Decisions (new this session)

| Decision | Rationale | Where locked |
|---|---|---|
| **RFC 7396 JSON Merge Patch for `/config` writes** | Partial update, idempotent, industry standard. Prevents stale-read-then-full-PUT data loss across UI tabs/sessions. | `kernel/config_manager.py::merge_patch` + `kernel/main.py::patch_config` |
| **Atomic YAML write (tempfile + os.replace + .bak backup)** | Crash safety; readers never see partial files; hand-edit recovery. Comments are lost on `yaml.safe_dump` — accepted for single-user local config. | `kernel/config_manager.py::ConfigManager.save` |
| **Null-guard on PATCH top-level sections** | RFC 7396 allows `null` to delete keys; `{"voice": null}` would wipe the voice section. Reject with 422 + named offending keys. | `kernel/main.py::patch_config` |
| **Method-aware UI dispatcher** | `/config` GET + PATCH both route to Rust; other methods fall through to Python. Foundation for any future endpoint-method split. | `ui/src/api/endpoints.ts::RUST_ENDPOINTS: {method, path}[]` |
| **Rust proxy with status preservation** | Forwards 422/etc. from Python unchanged; only 502 for network failure. UI sees semantic errors, not flattened 500s. | `src-tauri/src/backend/proxy.rs::proxy_patch_json` + `ProxyError` enum |
| **`/_internal/events` loopback-only** | Python→Rust push bridge, `ConnectInfo<SocketAddr>` + `is_loopback` guard, 403 for anything outside 127.0.0.0/8 and ::1. Prefix marks it as off-contract (not in UI dispatcher allow-list). | `src-tauri/src/backend/ingestion.rs` |
| **Lag-tolerant broadcast subscribers** | `RecvError::Lagged` is logged with skipped count, connection stays up. 256-slot capacity is the sweet spot. Matches Python's "no backfill on slow subscriber" semantics. | `src-tauri/src/backend/ws.rs::handle_socket_inner` |
| **Per-connection tracing span with monotonic `sub_id`** | Every WS log line carries the same id so operators can follow one client's story. | `src-tauri/src/backend/ws.rs` — `SUB_COUNTER: AtomicU64` |

## Confirmed Roadmap v2.1 (from `memory/project_roadmap.md`)

### Tier 1 — Non-tech distribution unblock
| # | Item | Status |
|---|---|---|
| 1 | Plan 2 Chunk 5 ChatInput migration | ✅ |
| 2 | Rust Phase 1 (stateless endpoints) | ✅ |
| 3 | Onboarding (7 chunks) | ✅ |
| 4 | Settings UI (5/5 chunks) | ✅ |
| 5 | Rust Phase 2 (WS + bus + bridge + UI flip + observability) | ✅ |
| 6 | Feedback channel | ⏳ **unblocked** |
| 7 | Rust Phase 3 voice pipeline | ⏳ **unblocked** |

### Tier 2 + Tier 3 — unchanged, see `memory/project_roadmap.md`.

## Pending Work

### Immediate options for next session (pick one)

**Option A (~60 min plan, ~3-5 days execution):** Write the Rust Phase 3 plan. This is the biggest remaining Tier 1 item — voice pipeline state machine moves from Python (`kernel/voice/pipeline.py`) into Rust, with ML inference calls delegated to Python over stdio bridge (spec §7). Phase 3 is the unlock for retiring Python's `/voice/*` endpoints and is the longest phase (~2 weeks execution per spec). Plan-before-code is mandatory.

**Option B (~30-60 min plan, ~2-3 days execution):** Write the Feedback channel plan (Tier 1 #6). Smaller scope than Phase 3 — a `POST /feedback` endpoint that pipes user reports into a local rotating log + structured file for friend-test debugging, a UI "Отправить лог разработчику" button anchored in the Advanced Settings section. Unblocks friend-distribution.

**Option C (smaller, ~45 min):** Live Tauri E2E smoke for Phase 2 — start Rust + Python together, open WS client, trigger `voice.pipeline` event, confirm UI Arc Reactor updates. Integration tests already verify the format on both sides but a live end-to-end validates the deployment path. Good pre-friend-test rigor.

**Option D (smallest, ~15-30 min):** Rebuild Premium installer. `dist_premium/kali-backend/` (7.84 GB from earlier session) is stale relative to Onboarding / Settings PATCH / Rust Phase 1-2 endpoints. Worth doing before any friend-distribution attempt.

**Recommended order:** B → C → A → D. B closes Tier 1 fastest (once its plan is executed); C gives confidence in the new wiring; A is the largest remaining piece; D is the final pre-distribution step.

Alternative: if the user wants to go fastest, A first (Phase 3 plan) since it's the one that has not been scoped yet.

### Critical — read before action

- `git log --oneline -12` should show (top to bottom): `7e0a36b` (Phase 2 Chunk 4), `dcb2ec4` (Phase 2 Chunk 3), `c4fc74d` (Phase 2 Chunk 2), `fee4fe1` (Phase 2 Chunk 1), `5c8e03f` (Phase 2 plan), `ccd602e` (Settings Chunk 3), `9308cd4` (PATCH proxy), `440b341` (PATCH Python), `ec15475` (Settings Chunk 2), `a67d72f` (morning handoff), `acc9127` (Settings Chunk 5), `4020cdd` (Settings Chunk 4).
- `cd src-tauri && cargo test` — must be 17 passed across 6 integration test binaries + 3 unit tests in `ingestion.rs`.
- `cd ui && pnpm test` — must be 61 passed / 1 skipped.
- `cd ui && npx tsc --noEmit` — must exit 0 with no output.
- `.venv/Scripts/python.exe -m pytest tests/kernel/test_rust_bridge.py -v` — 6 passed.

If any fails, **stop and investigate** before writing new code.

### Known gotchas (carry-forward — don't re-hit)

Inherited from morning handoff (all still valid):
1. **CSS var suffix bug** — `var(--j-cyan)22` is INVALID CSS. Always `color-mix(in srgb, var(--j-cyan) 13%, transparent)`.
2. **`.venv` can be partially broken** (dist-info without package code). Use `uv pip install --force-reinstall <pkg>`. Details in `memory/feedback_venv_pytest.md`.
3. **`uv run pytest` can re-sync venv** and undo force-reinstalls. Prefer `.venv/Scripts/python.exe -m pytest ...`.
4. **Flaky RAF test in jsdom** — `NumberReveal.test.tsx > eventually reaches the target value` is `it.skip`'d. Don't un-skip without `vi.useFakeTimers()`.
5. **Onboarding gate defaults to true** on fetch failure. Fresh installs always show onboarding. Tests mock `api.settings()` to avoid it.
6. **`mod backend` must be `pub mod backend`** in `src-tauri/src/lib.rs`. Already correct.
7. **Nested `@import` in CSS barrel** doesn't work with Vite + Tailwind 4 live. Flat imports in `ui/src/index.css`.
8. **Don't mix package managers** — always `pnpm add -D <pkg>` in `ui/`, never `npm install`.
9. **Tauri CSP** must allow BOTH 3005 and 3006. New Rust ports need `tauri.conf.json` CSP update.
10. **Rust `AppError` auto-converts from `anyhow::Error`** via `#[from]`. Use `?` on `anyhow::Result<T>`; don't `.map_err(Into::into)?`.

New this session (write these down):

11. **Rust integration tests run in parallel within one binary** — if tests mutate process-wide env vars (`KALI_CONFIG`, `KALI_PYTHON_BACKEND_URL`), serialize with a file-scope `static LOCK: Mutex<()> = Mutex::new(());`. Pattern is in `src-tauri/tests/config_endpoint.rs`.
12. **`axum::serve` must use `into_make_service_with_connect_info::<SocketAddr>()`** for the `ConnectInfo` extractor to resolve at runtime. `backend/mod.rs::serve()` already does this; any future test that hits `/_internal/events` needs the same incantation.
13. **Phase 2 requires BOTH Rust `:3006` AND Python `:3005` running** for full UI function. Vite-only preview (without Tauri) can't start Rust. For design-only verification without backends: Settings parent gates on `api.settings()` success, so it won't render sections if Python is down. Mock fetch in `preview_eval` to bypass.
14. **`yaml.safe_dump` strips comments from `kali.yaml`** — accepted loss for single-user local config. `.bak` sibling preserves prior contents including comments, so hand-edit recovery works. If comments ever become important (e.g., multi-user config), migrate to `ruamel.yaml` (adds dep).
15. **RFC 7396 null=delete** can wipe a section by accident. Guard in `kernel/main.py::patch_config` rejects top-level nulls with 422. Do NOT relax without adding an explicit reset endpoint.
16. **`axum` requires the `ws` feature flag** (not default in 0.7) — `axum = { version = "0.7", features = ["ws"] }`. Similarly `futures-util` needs `features = ["sink"]` for `SinkExt`.
17. **`proxy_patch_json` returns `ProxyError`, not `anyhow::Error`** — it distinguishes network failures (→ 502) from upstream non-success (→ forward status + body). If another PATCH/PUT proxy is needed, copy this pattern instead of reusing `proxy_get_json`.
18. **Per-file env-var test lock** serializes only within one test binary. Cross-binary tests can still race — if that becomes a problem, split tests across files (each binary is its own process).

## Critical Files (created/changed this session)

### Plan (committed)
- `docs/superpowers/plans/2026-05-09-rust-migration-phase-2.md` — 1046 lines, 4 chunks, full execution history.

### Python backend
- `kernel/config_manager.py` — `merge_patch()` helper (RFC 7396, 15 lines) + `ConfigManager.save()` with atomic write + `.bak`.
- `kernel/main.py` — `PATCH /config` handler with null-guard + Pydantic validation + event publish; bridge wired into lifespan startup/shutdown.
- `kernel/rust_bridge.py` — `RustEventBridge` (httpx.AsyncClient, 0.5s timeout, fire-and-forget, skips websocket-sourced) + `subscribe_to_bus()` helper.

### Rust backend
- `src-tauri/src/backend/event_bus.rs` — `EventBus` wrapper around `tokio::sync::broadcast` (capacity 256).
- `src-tauri/src/backend/models.rs` — serde `Event` + `WsMessage` mirroring Pydantic.
- `src-tauri/src/backend/ws.rs` — `/ws` handler with send/recv split, lag tolerance, `ui.command` echo, per-connection `sub_id` span.
- `src-tauri/src/backend/ingestion.rs` — `POST /_internal/events` with loopback guard.
- `src-tauri/src/backend/proxy.rs` — `proxy_patch_json` + `ProxyError` enum.
- `src-tauri/src/backend/http.rs` — `router_with_bus(Arc<EventBus>)` + legacy `router()` shim; PATCH /config forwarding; `ws_subscribers` in HealthResponse.
- `src-tauri/src/backend/mod.rs` — `serve()` uses `into_make_service_with_connect_info::<SocketAddr>()`, creates process-wide bus.
- `src-tauri/Cargo.toml` — `axum[ws]`, `futures-util[sink]`, `chrono`, `uuid`, dev-dep `tokio-tungstenite`.

### UI
- `ui/src/api/endpoints.ts` — `RUST_ENDPOINTS: {method, path}[]` + `resolveApiUrl(path, method)`.
- `ui/src/api/client.ts` — `updateConfig(patch: DeepPartial)` helper; `fetchJSON` threads method through dispatcher.
- `ui/src/api/runtime.ts` — `rustWsUrl` export, legacy `wsUrl` kept for rollback.
- `ui/src/api/websocket.ts` — connects to `rustWsUrl` instead of `wsUrl`.
- `ui/src/components/Settings/Settings.tsx` — token polish; mounts `<VoiceSettings />` between LLM and Advanced.
- `ui/src/components/Settings/sections/{LlmSettings,AdvancedSettings}.tsx` — token polish.
- `ui/src/components/Settings/sections/VoiceSettings.tsx` — new; wake_word input + mode HexFrame grid + auto_start toggle + dirty state + Применить CTA + restart hint.

### Tests
- `tests/kernel/test_config_manager.py` — +7 merge-patch cases, +5 save cases.
- `tests/kernel/test_main.py` — +5 PATCH /config cases (merge, validation, null-guard, malformed, event publish).
- `tests/kernel/test_rust_bridge.py` — new, 6 cases.
- `src-tauri/tests/config_endpoint.rs` — +3 PATCH cases (body round-trip, 422 preservation, 502 when down); file-scope `Mutex` for env-var isolation.
- `src-tauri/tests/ws_broadcast.rs` — new, 3 cases (fan-out, ui.command echo, malformed tolerance).
- `src-tauri/tests/ingestion.rs` — new, 4 cases (fan-out via WS, optional defaults, malformed 4xx, missing required 4xx).
- `src-tauri/tests/endpoints_contract.rs` — updated to ignore `ws_subscribers` in Rust-subset-of-Python check.
- `ui/src/api/__tests__/endpoints.test.ts` — +4 cases (method-aware routing, undeclared-method fallback, PATCH /config, default method).
- `ui/src/api/__tests__/runtime.test.ts` — new, 4 cases (URL defaults including `rustWsUrl`).
- `ui/src/components/Settings/sections/__tests__/VoiceSettings.test.tsx` — new, 6 cases.

### Memory (private, auto-loaded)
- `memory/project_roadmap.md` — v2.1 update, Tier 1 5/7 closed, items 6-7 unblocked.
- `memory/project_rust_migration.md` — Phase status table updated, Phase 0/1/1.5/2 all marked SHIPPED.
- `memory/MEMORY.md` — index updated with new handoff pointer.

## Test Status

- **UI:** 61 passing, 1 skipped (unchanged NumberReveal RAF-timing flake).
- **Rust integration:** 6 binaries, 17 tests total, all pass. +3 unit tests in `ingestion.rs` module.
- **Python kernel:** 40 passing in files affected this session (`test_main.py`, `test_config_manager.py`, `test_rust_bridge.py`); full suite 377 pass / 1 pre-existing flake `test_dispatch_tool_call` that passes in isolation.
- **Run commands:**
  ```bash
  cd ui && pnpm test                                # UI suite (~10 sec)
  cd src-tauri && cargo test                        # Rust integration (~3 min first time, ~10 sec cached)
  .venv/Scripts/python.exe -m pytest tests/kernel   # Python suite (~4 min because TTS tests load models)
  .venv/Scripts/python.exe -m pytest tests/kernel/test_main.py tests/kernel/test_config_manager.py tests/kernel/test_rust_bridge.py  # affected-only (~25 sec)
  ```

## Common Commands

```bash
# Start UI dev server
pnpm --prefix ui run dev

# Start Python backend dev
.venv/Scripts/python.exe -m kernel.entry

# Run Tauri + Rust + Python stack
npm --prefix ui run build && cargo run --manifest-path src-tauri/Cargo.toml

# Quick PATCH /config test against running Python
curl -s -X PATCH http://127.0.0.1:3005/config \
     -H "Content-Type: application/json" \
     -d '{"voice":{"wake_word":"kali"}}'

# Verify Rust /health exposes ws_subscribers (requires Rust running)
curl -s http://127.0.0.1:3006/health | jq

# Force-reinstall broken venv package
uv pip install --force-reinstall <package>

# Rebuild Premium backend (~10 min)
uv run --with pyinstaller python scripts/build_backend_premium.py

# Rebuild Premium installer (~40 min LZMA2)
scripts\build_installer_premium.bat
```

## Immediate Next Steps (for next agent)

1. **Greet user in Russian.** Acknowledge continuity from the 9-commit evening Phase 2 session.

2. **Verify state before any code:**
   ```bash
   git log --oneline -5             # top MUST be 7e0a36b
   cd src-tauri && cargo test       # 17 passed
   cd ui && pnpm test               # 61 passed, 1 skipped
   cd ui && npx tsc --noEmit        # exit 0
   ```
   If any fails — STOP and diagnose before continuing.

3. **Read `memory/project_roadmap.md` and `memory/project_rust_migration.md`** — both updated this session.

4. **Ask user which option: A (Phase 3 plan), B (Feedback plan), C (live E2E smoke), D (installer rebuild).** Recommended order B → C → A → D if user asks. Don't guess — let user pick.

5. **For any executed chunk, maintain the plan-before-code discipline.** If it's > 30 min or > 2 files, write the plan first.

6. **After each atomic chunk closes:** commit with a detailed message, verify tests green, move on. Don't batch commits.

## Pending rebuild / manual verification (not blocking)

- **Live Tauri E2E smoke for Phase 2** — integration tests cover the wire format on both sides; a live run with both backends simultaneously was not done this session because Rust requires Tauri which needs a graphics session. Worth a dedicated session after friend-distribution date is fixed.
- **Premium installer rebuild** — stale relative to Settings PATCH + Phase 1/2. Worth doing before friend-distribution but not yet.
- **Wake-word real-hardware test** — still skipped (see morning handoff). Blocked on CUDA onnxruntime mismatch that a `uv sync` should fix. ~30 min dedicated session before any friend-test.

## Communication Style for User

- **Russian for conversation**, English for code/paths/commits.
- **Short concrete answers** — tables for comparison, bulleted lists for plans.
- **"Предложи → обсудим → сделаем"** is a hard rule — propose, wait for "да"/"ок"/"давай", then execute.
- **Honest self-assessment** — if something isn't verified (e.g. live E2E, Premium installer rebuild), say so explicitly.
- **Ask before long-running builds** (installer ~40 min, PyInstaller ~10 min).
- **No emoji flood** — occasional ✅/⚠️/🎉 OK, don't make it festive.
- User values plan-before-code discipline and commits it back to docs.
- **User explicitly prefers canonical over pragmatic** when wiring foundational layers — see "Architecture decisions" above.

## GitHub State

- Remote: `github.com/VasilyKolbenev/kali-ai-os.git`
- Branch: `main`
- Latest commit: `7e0a36b`
- Tag: `v0.2.0-beta` (unchanged — tag bump deferred until Tier 1 fully closes and Premium installer rebuilds).
- No open PRs — solo dev.
- Working tree clean except `.claude/settings.local.json` (local, ignored) and `out/` (A/B voice output, ignored).

## User's Strategic Vision (unchanged North Star)

> KALI = voice-first AI OS that lets non-tech people (строитель/врач/офисник 30+) create AI agents by speaking. Distribution via UGC reels in TikTok/Reels. Desktop (Studio) → Mobile (Consumer) → Hardware device (CLIK + Starlink). **Rust backend + polished non-tech onboarding = differentiation vs OpenClaw (Python, developer-targeted).**

Monetization unchanged:
- Now → Q3 2026: Free + Pro $9.99/mo
- Q4 2026+: KALI Device $399 + $9.99/mo
- Seed criteria: K-factor > 1 + 50+ paying + D30 retention > 30%.

---

*Handoff created 2026-04-24 late evening after a 9-commit session that closed Phase 2 and brought Tier 1 from 3/7 to 5/7. Valid until the next significant commit batch. When in doubt, trust `git log` + this doc + `memory/*.md` — those are the canonical records.*
