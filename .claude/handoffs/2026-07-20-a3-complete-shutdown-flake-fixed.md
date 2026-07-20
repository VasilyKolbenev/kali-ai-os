# KALI handoff — A3 complete (non-blocking boot), GUI live gate PASS, shutdown flake fixed

Date: 2026-07-20 (Europe/Moscow). Author: Opus 4.8 session.

**One-line status:** A3 (Desktop trusted-alpha, non-blocking boot / OPUS-101) is
code-complete, the consolidated GUI live gate is fully PASS, and the last Codex
blocker (a non-deterministic shutdown test) is closed. Next critical-path work is
**OPUS-202 (secure updater)** — NOT started.

---

## 0. Repo / git state (verify first)

```
Branch : release/phase-a-desktop-alpha
HEAD   : e4642f5  (this handoff; UNPUSHED — awaiting owner short-review)
origin/release/phase-a-desktop-alpha : 6a3b86d  (all A3 code pushed)
main   : e3db43c  — DO NOT TOUCH, never merge here yourself
unpushed: 1 (only this handoff commit)
```

Verify on resume:
```bash
git rev-parse --abbrev-ref HEAD                       # release/phase-a-desktop-alpha
git rev-parse --short HEAD origin/release/phase-a-desktop-alpha main
git log --oneline origin/release/phase-a-desktop-alpha..HEAD   # should be just the handoff
git status --short                                    # see "do not touch" list below
```

**Pending decision:** the two shutdown-fix commits (`8737a53`, `6a3b86d`) are
pushed with Codex GO. This handoff commit `e4642f5` is NOT pushed — the owner
asked for a short review before pushing it. Push only on owner GO.

---

## 1. Read first, in this order

1. `AGENTS.md`
2. This handoff
3. `scratchpad/evidence/gate-run-2.md` — authoritative GUI-gate evidence (UNTRACKED)
4. `scratchpad/evidence/fresh-bundle-verify.md` — fresh premium onedir proof (UNTRACKED)
5. `scratchpad/evidence/topology-probe.md` — onedir single-process proof (UNTRACKED)
6. `docs/superpowers/plans/2026-07-17-a3-opus-101-nonblocking-boot.md` — A3 core plan (review #1–7)
7. `docs/superpowers/plans/2026-07-18-a3-commit4-honest-boot-degraded-surface.md` — commit-4 plan
8. `docs/public-launch/2026-07-17-prod-readiness-audit-opus-4.8.md` — full OPUS roadmap (what's left)

Evidence beats prose. If this handoff conflicts with a clean artifact run, the
live evidence wins.

---

## 2. What is DONE (all pushed to origin `6a3b86d`)

### OPUS-001 / OPUS-002 (freeze + version SoT)
- `9fbc336`, `1a299bc`, `9d94564` — release freeze + `scripts/release/version.py`
  single version source-of-truth (7 desktop sources) + safeguards.
- `1cb9921` — converge all desktop version sources to `1.0.0-rc3`.
- `a92c054` — add `ui/package.json` as the **7th** desktop version source
  (`version.py` reads top-level `version`, syncs without reformatting JSON).

### A3 / OPUS-101 — non-blocking boot (pure supervisor + thin Tauri adapter)
- `5e2df04` … `94448bc` — pure `src-tauri/src/startup.rs` supervisor with:
  typed liveness (Alive/Absent/Unknown), ownership by per-spawn instance-id,
  PORT_OCCUPIED / FOREIGN_BACKEND, bounded restart (`250→500→1000→2000→4000ms`,
  cap 5, 60s window) with give-up, terminate-retry, reap-fail-closed;
  `lib.rs` thin adapter; non-blocking shutdown (waiter thread + `prevent_exit`).
- `a49f1d1` — single-instance guard (`tauri-plugin-single-instance`, registered
  FIRST): second launch focuses existing window (unminimize → show → set_focus).
- `32b81e7`, `f5ca007` — **fail-closed backend artifact selection**: only
  `<exe-dir>/kali-backend/kali-backend.exe` **with a sibling `_internal/` dir**;
  onefile / `<repo>/dist` / cwd / ancestor fallbacks REMOVED (onefile spawned a
  bootloader grandchild that survived Child.kill() and held :3005). Type-split FS
  checks (`is_file` for exe, `is_dir` for `_internal`). Debug-only tri-state
  override `KALI_BACKEND_EXE` (`#[cfg(debug_assertions)]`, absolute path + exe +
  sibling `_internal`; Invalid → None, never falls back).
- `63f74f6`, `5be3280` — debug-only boot-delay lever `KALI_BOOT_DELAY_MS`
  (`#[cfg(debug_assertions)]`, DelayedProbe holds OwnedHealthy until deadline,
  never masks Foreign/errors, no sleep); its tests gated to debug builds.
- `788a4df` — mechanical split of resolver tests into
  `src-tauri/src/startup/tests/backend_path.rs`.

### A3 commit-4 — honest boot & degraded surface (UI)
- `f71326d` — add `@tauri-apps/api@^2` as a **direct** UI dependency (first
  direct Tauri IPC use from the UI).
- `91ade60` — pure `ui/src/lib/startupState.ts`: `classifyStartup(label)` →
  view kind (`booting`/`ready`/`degraded`/`failed`) + owner-approved RU copy.
  **10 user-visible overlay reasons**; `degraded_generic` is UNREACHABLE (kind
  fallback only); routing: `degraded:not_found` + `degraded:port_occupied` are
  RED despite the `degraded:` wire prefix; unknown non-null label → red
  `protocol_error`.
- `5bdab4c` — `ui/src/hooks/useStartupState.ts`: subscribe-before-invoke,
  listen-settlement-gated poll, event-authoritative reconciliation, cleanup.
- `4271f67` — `StartupSurface` overlay + `App.tsx` wiring (classification read
  BEFORE the onboarding early-return; timer-driven terminal `kernelStage===2`
  removed → terminal owned only by Rust startup-state).

### Shutdown-flake fix (last Codex blocker — CLOSED)
- `8737a53` — flaky `shutdown_pending_prevents_starts_one_waiter_completes_once`
  (145 passed / 1 failed under full-suite load) made deterministic. Root cause:
  `sleep(60+80ms)` used as a signal that a DETACHED waiter thread had processed
  the ack. Fix: minimal test seam
  `spawn_exit_waiter(...) -> (ExitDecision, Option<JoinHandle>)`;
  `on_exit_requested` is a thin wrapper returning `.0` (drop handle = detach,
  behaviour identical). Tests `join()` the waiter. Same anti-pattern also fixed
  in `shutdown_disconnected_...`.
- `6a3b86d` — closed two Codex re-review gaps:
  - **P1 (production adapter):** `on_exit_requested_wrapper_completes_then_allows`
    drives the REAL `on_exit_requested()` (not the seam) via a completion channel;
    proves the shipping wrapper starts the waiter and, after done, returns Allow
    with no new callback.
  - **P2 (deterministic timeout-cycle):** observer seam
    `wait_for_ack_with_timeout_observer(rx, tick, on_timeout)` (production
    `wait_for_ack` delegates with a no-op). Test waits for an explicit
    "survived ≥1 Timeout" signal, THEN sends the ack, THEN the waiter must return
    Completed (delivered over a bounded outcome channel). Order proven with no
    sleep. Replaces the old `sleep(50ms)` proof.
  - Mutation-verified ×5 (wrapper-stops-spawning → adapter RED while seam stays
    green; Timeout→Disconnected; ack-after-Timeout dropped → bounded watchdog RED;
    second waiter; Disconnected→Completed).
- **Production shutdown semantics were NOT changed by either commit.**

---

## 3. GUI live gate — fully PASS (2026-07-20; evidence in `scratchpad/evidence/gate-run-2.md`)

Ran on shipping artifacts. Two stages under `scratchpad/` (UNTRACKED, ~5.8 GB):
- `scratchpad/gate-stage/` = release `kali-desktop.exe` + adjacent `kali-backend/`
  onedir (with `_internal/`) — the real user layout.
- `scratchpad/gate-stage-bare/` = only `kali-desktop.exe` (no adjacent onedir) —
  used to trigger `not_found`.
- `scratchpad/health_stub.py` = tiny `/health` stub for S3 foreign/absent cases.

Scenarios (all PASS):
- **S1** first-paint ≤1s (823 ms) then reaches Ready.
- **S2** setup does not wait for health (first paint 356–823 ms vs health 20–291 s).
- **S3** ownership: matched (real backend), foreign-id, absent-id (stub) → amber
  `foreign_backend` overlay, no self-spawn.
- **S4** :3006 occupied → PortOccupied (os error 10048) → RED "Локальный сервис занят".
- **S6** desktop → onedir → close: zero orphan, ports free.
- **S7** crash → exactly one respawn, new instance-id, ownership.
- **S8** single-instance: second instance dies, one backend, window restored;
  **focus owner-observed** (Windows blocks background focus-steal from automation).
- **GaveUp**: crash-loop → exactly `cap+1 = 6` spawns, one `failed:gave_up` RED,
  no crash-storm.
- **close-during-spawn**: graceful WM_CLOSE strictly AFTER the backend-child
  appeared (t_window +0.11s, t_child +2.90s, t_close +2.92s) → desktop + child
  both terminated, zero orphan.
- **resp-45s**: no terminal-red across 45s PythonStarting, full interactive UI,
  reaches Ready; drag/click/scroll responsiveness **owner-observed**.
- Live-confirmed **4/10** overlay reasons (foreign_backend, port_occupied,
  not_found, gave_up) + both surface colors. The other 6 (rust_startup, crashed,
  spawn_failed, process_unknown, generic-failed/KillFailed, protocol_error) are
  unit-covered and not externally triggerable without code injection — Codex
  ruled: **no temporary fault-injection hooks.**

---

## 4. Gates (green on `6a3b86d`)

- Rust `cargo test --lib --offline --locked`: **147 passed, 0 failed** (5 full
  consecutive passes). NOTE: earlier Opus reports said 146 — the correct current
  count after the P1 adapter test is **147**.
- focused shutdown/ack tests ×50, each run really ran 7 tests / 7 passed
  (non-zero count verified — see gotcha about `--exact`).
- `cargo test --release --lib --no-run --offline --locked`: Finished, 0 warnings.
- `cargo check --bins --offline --locked`: Finished, 0 warnings.
- UI: `pnpm --dir ui exec vitest run` 203 passed + `pnpm --dir ui exec tsc -b --noEmit` clean.
- Python: `.venv\Scripts\python.exe -m pytest tests/kernel/test_main.py -q` 57 passed.
- rustfmt `--config skip_children=true` clean on changed leaves; `git diff --check` clean.

---

## 5. What is LEFT (OPUS roadmap — `docs/public-launch/2026-07-17-prod-readiness-audit-opus-4.8.md` §9)

Critical path: OPUS-001/002 ✅ → **OPUS-101 ✅ (=A3)** / 102 / 103 → 201/202/203 →
301/302/303/304 → 401.. / 501.. → 601..603 → clean-device RC.

**Immediate next candidate = OPUS-202 (owner has flagged it repeatedly):**
- Files: `src-tauri/src/backend/updater.rs`, tauri config, release workflow.
- Temporarily disable auto-execution of the custom updater; migrate to Tauri
  signed updater OR an independent signed-manifest chain; add tamper / wrong-key /
  replay / downgrade / expired-manifest tests.
- Acceptance: a hash placed next to a swapped EXE is NOT sufficient for acceptance.
- **A3-relevant nuance already surfaced:** `updater.rs` calls `std::process::exit()`,
  which bypasses graceful shutdown — OPUS-202 should also remove that so the
  non-blocking shutdown path from A3 is honored.

**Other remaining (not started):**
- **OPUS-102** — lifespan without heavy voice prewarm: single-flight
  `ModelCoordinator`, one shared STT owner, no torch.hub/HF network on each start,
  timeout/cancellation/degraded. Acceptance: `/live` ≤1s, `/ready` text ≤3s,
  voice readiness independent. (Deliberately OUT of A3.)
- **OPUS-103** — clean frozen build/stage (unique build id, manifest-driven asset
  copy, smoke from exact stage + clean VM, full offline startup).
- **OPUS-201/203** — Windows release signing (needs owner cert) / reproducible
  dependency gate (pin ort, --locked, SBOM).
- **OPUS-301** — provider model registry: centralize defaults, replace retired
  Anthropic model, sync desktop/mobile/UI, capability validation + deprecation test.
- **OPUS-302/303/304** — data-map/privacy, voice/asset license cleanup, community
  bundle containment (fail-closed native import for alpha).
- **OPUS-401+ / 501+** — Android release AAB / iOS, in parallel after
  version/privacy/model registry.

**Human blockers the model cannot resolve:** Windows code-signing cert; Google
Play account + upload key + Data Safety; Apple dev account + macOS runner; owned
HTTPS domain; legal sign-off on voice/model/IP + policy text; real devices + clean VM.

---

## 6. Resume / verify commands (Windows, this machine)

Env for every cargo call: `$env:__COMPAT_LAYER='RunAsInvoker'` + `--offline --locked`.

```powershell
# Rust unit gate (authoritative)
$env:__COMPAT_LAYER='RunAsInvoker'
cargo test --manifest-path src-tauri/Cargo.toml --lib --offline --locked          # 147 passed
cargo test --manifest-path src-tauri/Cargo.toml --release --lib --no-run --offline --locked
cargo check --manifest-path src-tauri/Cargo.toml --bins --offline --locked

# Focused shutdown/ack tests (substring filter — NOT --exact, see gotcha)
cargo test --manifest-path src-tauri/Cargo.toml --lib --offline --locked -- shutdown wait_for_ack on_exit_requested

# UI + Python gates
pnpm --dir ui exec vitest run
pnpm --dir ui exec tsc -b --noEmit
.venv\Scripts\python.exe -m pytest tests/kernel/test_main.py -q

# Rebuild premium onedir backend (5.83 GB; needed to re-run GUI gate)
$env:__COMPAT_LAYER='RunAsInvoker'
uv run --with pyinstaller python scripts/build_backend_premium.py   # -> dist_premium/kali-backend/

# Rebuild desktop (debug needs KALI_BACKEND_EXE override; release embeds ui/dist)
cargo build --manifest-path src-tauri/Cargo.toml --bins --offline --locked        # debug
& "ui\node_modules\.bin\tauri.cmd" build --no-bundle                              # release exe
```

GUI-gate re-run: copy `dist_premium/kali-backend` next to a release
`kali-desktop.exe` in a clean stage dir; run WITHOUT a dev server; screenshots via
`PrintWindow(PW_RENDERFULLCONTENT)` on the `class="Tauri Window"` window (see gotchas).

---

## 7. Key files

- `src-tauri/src/startup.rs` — pure supervisor (typed liveness, backoff, resolver,
  DelayedProbe/boot-delay lever). Tests: `src-tauri/src/startup/tests.rs` +
  `startup/tests/{backend_path,backend_override,boot_delay}.rs` (some `#[cfg(debug_assertions)]`).
- `src-tauri/src/lib.rs` — Tauri adapter: `on_exit_requested`/`spawn_exit_waiter`,
  `wait_for_ack`/`wait_for_ack_with_timeout_observer`, `ShutdownControl`, `Waker`,
  `RealProbe`/`classify_health`, `RealSpawner`, `find_backend`,
  `resolve_backend_path`/`resolve_backend_override`, `state_label`, `get_startup_state`.
  Tests: `src-tauri/src/tests.rs`.
- `ui/src/lib/startupState.ts`, `ui/src/hooks/useStartupState.ts`,
  `ui/src/components/Startup/StartupSurface.tsx`, `ui/src/App.tsx`.
- `scripts/release/version.py` (+ `tests/scripts/test_release_version.py`,
  `_guard_fixtures.py`).
- `scripts/build_backend_premium.py`, `scripts/frozen_smoke.py`.
- Evidence (untracked): `scratchpad/evidence/*.md` + PNG; stages under `scratchpad/`.

---

## 8. Gotchas (hard-won this session — read before running anything)

- **`--exact` + short test name matches 0 tests and cargo still exits 0** → a loop
  counting exit codes falsely reports "pass". Full path is `tests::<name>`. Filter
  with a **substring (no `--exact`)** or the full `tests::` path, and always assert
  the printed test count is non-zero (e.g. require `test result: ok. N passed`).
- **The shutdown flake only reproduces under full-suite scheduler load.** Isolated
  focused runs pass 50/50 on an idle machine. Deterministic repro = throwaway
  150 ms `sleep` inside the on_complete closure (models delayed scheduling) → the
  old test reliably RED. See [[feedback-dev-machine-masks-truth]].
- **rustfmt on a crate-root recurses the whole module tree** → collateral in
  `backend/*.rs`. Always `rustfmt --edition 2021 --config skip_children=true <file>`
  on individual leaf files; check `git status src-tauri/src/backend/`.
- **cargo touches `Cargo.toml`/`Cargo.lock` with a phantom LF/CRLF-only change**
  (empty `git diff`). Revert with `git checkout -- src-tauri/Cargo.toml` before staging.
- **Debug vs release frontend:** Tauri v2 debug profile loads `devUrl`
  (`http://localhost:1420`) — needs a Vite server; release embeds `ui/dist`. The
  boot-delay lever exists only in debug. `.claude/launch.json` (dirty, untracked
  changes) has a `ui-dev-tauri` entry on port 1420 for that — do not commit it.
- **Screenshots:** PowerShell is not DPI-aware by default → `SetProcessDPIAware()`
  first. `Get-Process.MainWindowHandle` points at the single-instance plugin's
  helper window (`class=com.kali.desktop-sic`, 15×15), NOT the app — enumerate
  windows and pick `class="Tauri Window"`. Use `PrintWindow(PW_RENDERFULLCONTENT=2)`
  (CopyFromScreen grabs whatever overlaps).
- **`.ps1` with Cyrillic must be UTF-8 with BOM** or Windows PowerShell 5.1 parses
  it as ANSI and breaks. In inline PS, `"$i:"` is parsed as drive `i:` — use `${i}`.
- **Windows Job Object (zero-orphan on hard-kill) is a deferred fast-follow**, not
  part of A3. onedir is single-process (topology-probe proved kill root → 0 orphan);
  the orphan seen with the old onefile layout is what the fail-closed resolver
  now prevents.

---

## 9. Git / dirty discipline (STRICT)

- Stage only explicit paths. NEVER `git add .` / `-A` / `reset` / `checkout` (except
  reverting the phantom Cargo.toml) / `clean`.
- **Do NOT touch or commit these pre-existing dirty/untracked files:**
  - `docs/public-launch/2026-07-17-opus-4.8-session-start.md` — owner-approved dirty
    **Product Evolution Track**.
  - `.claude/launch.json` — local dev tooling (has the 1420 Vite entry).
  - `scratchpad/` — untracked gate evidence + 5.8 GB stages (safe to delete/rebuild).
  - assorted mobile codegen, `uv.lock`, `*.tsbuildinfo`, `.pnpm-store/`, log files.
- Do NOT touch `main`. Do NOT merge to main yourself.
- Boundaries for the next task unless it explicitly says so: updater / OPUS-102 /
  provider registry / voice / models / UI.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Do NOT amend pushed commits. `e4642f5` (this handoff) is unpushed; push only on
  owner GO.
- Workflow discipline (owner-binding): plan-first → adversarial review → TDD →
  implement → review → fix-loop → evidence (live data / mutation / clean env).
  Mutation evidence is mandatory (mutate → exactly the right test reddens → revert).
  Stop for Codex review at each gate; small commits; Russian, concise.
