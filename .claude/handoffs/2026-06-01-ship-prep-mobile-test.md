---
handoff_date: 2026-06-01
project: KALI — ship-prep (commit safety, bug-hunt, security plugin, v4 installers, mobile E2E)
branch: main
latest_commit: cc4a78e (pushed to origin)
origin_main: cc4a78e (in sync)
prior_handoff: .claude/handoffs/2026-05-05-roadmap-v214-and-premium-v2-ready.md
status_summary: 11 commits this session all pushed. Lite v4 + Premium v4 BACKEND built. Mobile E2E in progress — app builds/installs/runs, paused on emulator render fix (Impeller, uncommitted).
---

# KALI Session Handoff — 2026-06-01

After a 9-day gap (May 22→Jun 1) during which Vasily did heavy work in **Antigravity** (mobile Flutter app, 4 agents, multi-provider llm_router, Canvas, SAST fixes) — all of it was **uncommitted**. This session: consolidated everything into git, ran a pre-release bug-hunt, enabled the security plugin, established a working principle, rebuilt installers, and started mobile E2E.

## TL;DR — where we are

- **Git is safe.** 11 logical commits, all pushed to `origin/main` (`cc4a78e`). 9 days of Antigravity work no longer at risk.
- **Lite v4 installer** built today: `dist_lite/KALI-Lite-Setup-0.2.0-beta.exe` (112 MB, current code).
- **Premium v4 backend** built (PyInstaller `--collect-all transformers`, exit 0) — but **installer NOT yet produced** (stage + Inno Setup still to run).
- **Mobile E2E in progress (P2):** the Flutter app **builds, installs, and runs without crashing**. Paused on two emulator issues — one fixed (uncommitted), one worked around.
- **Active blocker right now:** mobile app rendered a **black screen** because `EnableImpeller` was `false` → **fixed in `mobile/android/app/src/main/AndroidManifest.xml` (UNCOMMITTED)**. Needs an APK rebuild to verify, then commit.

## What this session delivered

### Commits (11, all pushed to origin/main)
| SHA | What |
|---|---|
| `37df019` | docs: VISION rework, SESSION_LOG, v3 handoffs, .gitignore (worktrees + spec) |
| `e82c7dd` | feat(llm): 7-provider router (Gemini native + OpenAI-compat DeepSeek/Groq/Mistral) + SAST |
| `304d218` | feat(kernel): long_term_memory + remote_pipeline (mobile WS) + voice tweaks |
| `c640ed1` | feat(kernel): main.py canvas-forward + /dashboard + 0.0.0.0 LAN bind + rust bridge |
| `92518ff` | feat(agents): live-canvas, messenger-hub, automation-scheduler, web-surfer |
| `e991083` | feat(ui): Canvas widgets, ModelsDownloadStep, multi-provider + SAST (XSS/proto-pollution) |
| `e7969f3` | feat(mobile): Flutter app — 8 screens, 5 langs, 7 providers (146 files) |
| `d1a3903` | build: v3 installer infra, run_server.py, diag tools |
| `947109f` | test(ui): onboarding step-order fix (models-download) |
| `a8edd82` | chore(security): enable security-guidance plugin project-wide + KALI rules |
| `cc4a78e` | fix(voice): cap remote audio buffer → prevent OOM DoS over LAN /ws (from bug-hunt) |

### Installers
- **Lite v4**: `dist_lite/KALI-Lite-Setup-0.2.0-beta.exe` — 112 MB, Jun 1 13:35, current code. Cloud-voice (no local F5/whisper/onnxruntime).
- **Premium v4 backend**: `dist_premium/kali-backend/` — built today (~8.6 GB, exit 0). **Installer not built yet** — run stage + Inno (see "Pending" P5).
- Frontend (`ui/dist`) + Tauri (`src-tauri/target/release/kali-desktop.exe`) rebuilt today → **warm** for Premium installer (skip rebuild).

### Pre-release bug-hunt (P1, Workflow — generator→validator)
- 21 agents, ~1.17M tokens, 15.5 min. **17 findings → 1 confirmed ship-blocker** (16 adversarially dismissed as false-positives/non-blockers).
- Fixed: unbounded audio buffer DoS in `remote_pipeline.py` (`cc4a78e`). Controller verified the finding in code before fixing.

### Security-guidance plugin (committed a8edd82)
- `.claude/settings.json` → `enabledPlugins: security-guidance@claude-plugins-official` (project-wide).
- `.claude/claude-security-guidance.md` → KALI threat model.
- `.claude/security-patterns.json` → deterministic per-edit patterns (key prefixes, agent-codegen exec).
- **⚠️ Vasily STILL must run interactively:** `/plugin install security-guidance@claude-plugins-official` (choose **user** scope) then `/reload-plugins`. The settings.json only enables it for the repo; the user-scope install bootstraps the venv + activates on this machine.

### Memory updates (auto-memory, persists across sessions)
- `feedback_workflow_principle.md` (NEW) — **binding working principle**: plan-first gate (propose → Vasily edits → add constraints/success-criteria/key-files/checks → THEN run) + generator→validator execution. Never fire Workflow before plan approval.
- `project_competition.md` — added Competitor 4 (OpenHuman 30k⭐) + Competitor 5 (OpenJarvis) + strategic takeaway. KALI's stack VALIDATED by both. Steals (Memory Tree, context compression, aggressive local routing) deferred post-launch. Anti-pivot refinement: narrow consumer integrations (Gmail/Calendar/Telegram) defensible; dev integrations (GitHub/Notion/Jira/Slack/Figma) = NO.
- `MEMORY.md` — pointers updated (will update to point at THIS handoff).

### Chips spawned (don't lose — appear as clickable tasks)
1. `/ws` pairing-token (unauthenticated WS on 0.0.0.0 — before wide mobile release).
2. `print→logging` cleanup in `remote_pipeline.py`.
3. anti-SSRF URL validation in `web-surfer` agent (defense-in-depth, not reachable today).

## 🔴 ACTIVE TASK — Mobile E2E (P2), exactly where we paused

**Goal:** test the Flutter mobile app against the backend (Android Studio emulator).

**Established facts:**
- App package: `com.example.kali_mobile/.MainActivity`.
- Mobile connects to **`ws://10.0.2.2:3006/ws`** + **`http://10.0.2.2:3006`** (port 3006; `10.0.2.2` = emulator→host loopback). Hardcoded in `mobile/lib/core/websocket_client.dart` + `http_client.dart`.
- The app **builds, installs, and runs — NO crash** (verified via adb: "Displayed/Fully drawn", no Dart/FATAL errors).

**Two problems found:**
1. **App launched on secondary Display 2** (emulator has a virtual "Emulator 2D Display" 720×1280 besides main Display 0 1080×2400). That's why the main emulator window showed only the home screen. **Workaround:** `adb shell am start --display 0 -n com.example.kali_mobile/.MainActivity`. **Permanent fix:** emulator Extended controls (⋮) → Displays → remove the secondary display, OR cold-boot.
2. **Black screen** when on Display 0 = `EnableImpeller=false` in AndroidManifest forced legacy GL renderer (black on this API-37 emulator). **FIXED (uncommitted):** `mobile/android/app/src/main/AndroidManifest.xml` line 11 `false → true`. **Needs APK rebuild to take effect** (manifest change is not hot-reloadable).

**Next steps to finish mobile E2E:**
1. Rebuild the APK so the Impeller fix lands: in Android Studio Stop ■ then Run ▶ (or `flutter run`). Flutter CLI is NOT on the plain PATH — use Android Studio's Run, or find flutter via the IDE's configured SDK.
2. After install, force the app onto the main display: `adb shell am force-stop com.example.kali_mobile; adb shell am start --display 0 -n com.example.kali_mobile/.MainActivity`.
3. Screenshot to verify: `adb exec-out screencap -p > emu_screen.png` then view. Expect the **Connection screen** (IP field `10.0.2.2` + Connect).
4. Tap **Connect** → should go to Dashboard.
5. Test in order: Dashboard (weather/tasks/greeting) → Chat (type "Привет" → LLM reply) → Settings (7 providers, language, persist) → Voice (record → STT/TTS).
6. Watch backend logs for each request. If green → **commit the Impeller fix** (`fix(mobile): enable Impeller to fix black screen on Android`).

**adb path:** `$HOME/AppData/Local/Android/Sdk/platform-tools/adb.exe` (device `emulator-5554`).

**flutter-run gotcha:** the repeated `Error connecting to the service protocol ... DartDevelopmentServiceException` is a Flutter+emulator **DDS tooling** issue — it does NOT crash the app (the APK installs+runs fine). Use `flutter run --release` to avoid DDS entirely, or just ignore it and drive the installed app via adb.

## ⏳ Pending work (prioritized — the "ship before competitors" P-roadmap)

| P | Task | Status | Owner |
|---|---|---|---|
| P0 | Push to origin | ✅ | — |
| P1 | Pre-release bug-hunt | ✅ 1 fix | — |
| P3 | Fix ship-blockers | ✅ | — |
| **P2** | **Mobile E2E** | 🔴 in progress (Impeller fix uncommitted; see above) | Vasily+Claude |
| P2 | Desktop E2E + voice | ⏳ not started | Vasily+Claude |
| P4 | Gate A (voice.engine=rust cutover + rehearsal) + Gate B (voice-builder 5 prompts) | ⏳ needs voice working | Vasily+Claude |
| P5 | **Premium v4 installer** (backend ✅, run stage + Inno Setup) | ⏳ autonomous | Claude |
| P5 | Desktop full reinstall test (validate Premium v4 bundle standalone — never confirmed before) | ⏳ | Vasily+Claude |
| P6 | Release + promote | ⏳ | Vasily |

**Deferred post-launch (NOT now):** Memory Tree, context compression, aggressive local routing (the competitive steals).

## Running background processes (at handoff)
- **Dev backend on `0.0.0.0:3006`** (uvicorn `kernel.main:create_app`, ProactorEventLoop) — still running for the mobile test. If gone, restart with:
  ```
  cd C:\Users\User\Desktop\Jarvis
  .venv/Scripts/python.exe -c "import asyncio,uvicorn; asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy()); import uvicorn.loops.asyncio; uvicorn.loops.asyncio.setup=(lambda:None); uvicorn.run('kernel.main:create_app', host='0.0.0.0', port=3006, factory=True)"
  ```
  (Note: `run_server.py` HARDCODES 127.0.0.1:3005 and ignores KALI_HOST/KALI_PORT — that's why the inline uvicorn above is used for :3006. Fixing run_server.py to read env is a nice-to-have.)

## Uncommitted working-tree state (intentional)
```
 M mobile/android/app/src/main/AndroidManifest.xml   ← Impeller fix (verify+commit next session)
 M .claude/settings.local.json                        ← local Claude config (do NOT commit)
 M ui/tsconfig.tsbuildinfo                             ← build cache (ignore)
?? fix.py, test_whisper.py                             ← throwaway scratch (ignore or delete)
```

## Key decisions & binding rules (carry forward)
- **Working principle (binding, 2026-06-01):** plan-first + generator/validator. See `memory/feedback_workflow_principle.md`. Propose plan → Vasily edits → 4 inputs (constraints/success-criteria/key-files/checks) → then execute. Never fire Workflow before plan approval.
- **Ship-first strategy:** beat competitors by shipping the current solid product, NOT by adding the competitive steals. Defer Memory Tree/compression/routing.
- **Anti-pivot (v2.14, still binding):** no dev/design integrations. Consumer integrations (Gmail/Calendar/Telegram) are a separate, defensible question — not auto-pursued.
- Direct-to-main commits (solo dev). Docs/config commits OK without go. Feature/fix commits wait for "ок/го/давай/поехали".
- `.venv/Scripts/python.exe -m pytest` (not uv run). `KALI_SKIP_PREWARM=1` stays in conftest.
- Russian-first chat; code + tech terms English.

## Verify-state for next session
```bash
cd C:/Users/User/Desktop/Jarvis
git log --oneline -3        # top = cc4a78e, origin in sync
git status --short          # expect: AndroidManifest.xml (M) + the intentional bits above

.venv/Scripts/python.exe -m pytest tests/kernel/builder/ tests/kernel/test_builder_endpoints.py \
  tests/kernel/voice/ tests/kernel/test_voice_transcribe_endpoint.py tests/kernel/test_main.py -q
# Expected: 95 passed

cd ui && pnpm test && npx tsc --noEmit   # Expected: 98 passed | 1 skipped, tsc 0
```

## Critical files/paths
- Mobile net: `mobile/lib/core/websocket_client.dart` (:3006 hardcoded), `http_client.dart`, `connection_screen.dart` (IP default 10.0.2.2)
- Impeller fix: `mobile/android/app/src/main/AndroidManifest.xml:9-11`
- Premium build: `scripts/build_backend_premium.py` (+collect-all transformers), `scripts/installer_premium.iss`, `scripts/build_installer_premium.bat`
- Lite build: `scripts/build_backend_lite.py`, `scripts/installer_lite.nsi`
- Backend entry (dev): inline uvicorn on :3006 (run_server.py is :3005-hardcoded)
- Security config: `.claude/settings.json`, `.claude/claude-security-guidance.md`, `.claude/security-patterns.json`
- adb: `$HOME/AppData/Local/Android/Sdk/platform-tools/adb.exe`

---
*Handoff created 2026-06-01. Resume: finish mobile E2E (rebuild APK for Impeller fix → display 0 → connect → test), then Premium v4 installer + desktop reinstall + Gates A/B → release.*
