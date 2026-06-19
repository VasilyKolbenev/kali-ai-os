---
handoff_date: 2026-06-19
project: KALI — investor demo-readiness pass + honest market assessment + mobile track started (full parity, no cuts)
branch: main
latest_commit: see `git log --oneline -1` (≈55+ commits ahead of origin 198c31d — NOTHING PUSHED)
origin_main: 198c31d
prior_handoff: .claude/handoffs/2026-06-11-voice2-masterskaya-nav2-memory-accent.md
status_summary: >
  Two arcs this session. (1) Investor-demo readiness: a full "всё в кучу"
  build round (agent permissions + honest statuses, voice record window,
  STT prompt, TTS fast-first-chunk, chat states, persona honesty) → then a
  live demo-readiness verification that found+fixed 3 real bugs (weather
  Cyrillic city, sticky agent error-status, news key path) → desktop installer
  rebuilt + verified (4.61GB). Honest market-readiness assessment delivered
  (vetted: the "API keys leaked" alarm was FALSE — .env never committed).
  Founder's-Playbook pitch insights added. (2) Mobile track STARTED toward
  full parity (Vasily: no cuts, mobile must be as useful as desktop): baseline
  APK on kali_test_34, live /dashboard backend, emulator↔backend bridge proven
  (mobile connects + renders). Backend rebuild was IN FLIGHT at handoff.
---

# KALI Session Handoff — 2026-06-19

## TL;DR (read first)
- **Investor demo is in a few days, LIVE on Vasily's PC. Desktop is ~90% demo-ready** — installer built + verified (`dist_premium/installer/KALI-Premium-Setup-0.2.0-beta.exe` + 3×.bin, 4.61GB).
- **Demo playbook ready:** `docs/demo/2026-06-15-investor-demo-playbook.md` (script, risk list, Founder's-Playbook pitch, traffic-light, morning checklist). READ IT before the demo.
- **Mobile track started, scope = FULL PARITY, NO CUTS.** Done: baseline APK (`ai.kali.mobile`), live `/dashboard`, emulator↔backend bridge. Next: Мастерская port (#15) → voice builder (#16) → memory/canvas/activity/share (#18-21).
- **Honest market readiness (vetted):** demo ~90% · closed-beta/friend-distribution ~70% · public mass-market (UGC+mobile+consent) ~40%. Don't exaggerate to the investor — the playbook has the honest framing.
- **NOTHING pushed.** All commits local on `main`.

## State at handoff
- **HEAD:** run `git log --oneline -1`. This session's commits (in order): build round (`2b49c5e` agents permission/config-status, `85fab75` store/chat/persona), `3b0a6fc` demo fixes (weather Cyrillic + sticky-error + news), `23de7d6` demo playbook, `abdfcad` playbook pitch, `57ee9e9` mobile applicationId+plan, `bad1aef` live dashboard, plan-scope commit, mobile parity tasks. ~Several more.
- **Working tree:** scratch only (verify_demo.py / verify_stt.py / verify_builder.py — GITIGNORED; mobile_*.png screenshots — untracked scratch).
- **Running at handoff (may be gone if Vasily rebooted — git + premium_stage persist):**
  - Staged desktop app (`dist_premium/premium_stage/kali-desktop.exe`) → serving :3006 (Rust) + :3005 (Python) for the mobile bridge.
  - Emulator `kali_test_34` (emulator-5554) with the mobile app installed + connected.
  - **Backend rebuild IN FLIGHT** (task `bf3z01ox9`, `uv run --with pyinstaller python scripts/build_backend_premium.py`) — rebuilding the frozen backend so the live `/dashboard` (and all source fixes) reach mobile. **ON RESUME: check if it finished; if so, restage backend into premium_stage, relaunch staged desktop, re-verify mobile dashboard shows +21°C real (not +22°C mock).**

## What this session did (the arc)
1. **Build round "всё в кучу"** (Vasily wanted everything fixed at once, mandate to decide defaults myself):
   - **Agents:** «Включить» now grants permission to ANY agent (was 403 for non-builtin — currency/news showed «Работает» but did nothing). Idempotent approve on execute. New `kernel/agent_keys.py` registry + `GET /agents/config-status` → honest «Нужна настройка». `/settings` accepts agent keys (whitelist). UI: 3rd card state «Нужна настройка» + inline key dialog → auto-enable. (`2b49c5e`, `85fab75`)
   - **Voice:** record-window silence 1s→2.5s (`KALI_SILENCE_MS`); STT domain initial_prompt + softer vad_filter (0.3) for missed words (`KALI_STT_MODEL` env to A/B small/medium); SentenceBuffer emits FIRST sentence immediately (fast first audio), merges the rest. (`848d78a`)
   - **Chat/persona:** «PROCESSING»→«Джарвис думает…»; persona stops narrating fake background actions, routes agent-creation to «Создать голосом». (`85fab75`)
2. **Live demo-readiness verification (source backend :3005)** → found+fixed 3 real bugs:
   - **weather Cyrillic** — geocoding `language=en` silently failed on «Москва» (= exactly what STT yields). Fixed → `language=ru` (resolves Cyrillic AND Latin). Both agent.py + scripts/agent.py. (`3b0a6fc`)
   - **sticky agent error-status** — one bad call (bad city, unknown action) flipped an agent to permanent «error». Now per-call failures don't change process status. (`3b0a6fc`)
   - **news key path** — needed NEWS_API_KEY with no setup path → added to registry + curated «Нужна настройка» card. (`3b0a6fc`)
   - Verified live: currency real rates, weather «Москва»→21°, STT transcribes RU, persona routes correctly, builder deploys a real skill to disk.
   - **Desktop installer rebuilt + "Successful compile"** (4.61GB).
3. **Honest market assessment** (3 parallel Explore agents: mobile gap, hardcode, vision) — VETTED myself:
   - 🔴→🟢 **«API keys committed» = FALSE.** `.env` is gitignored, `git log --all -- .env` empty → never committed. Keys are LOCAL only. Do NOT alarm Vasily.
   - «tests broken» = overstated (subagent env missing aiosqlite; targeted tests green all session; full-suite = known DEV-1).
   - Real minor hardcodes (NOT blockers): `agent_runtime.py:54` http-agent `localhost:8080` (no http agents exist), weather «Moscow» fallback, CORS hardcoded (SEC-2/LAN, known), ports (overridable).
   - Real gaps for PUBLIC launch: safe-generativity lock 4 (deploy w/o dry-run/voice-consent), UGC share surface not wired, no metrics framework, CC-BY-NC license, `main.py` 2154-line god object.
4. **Founder's Playbook** (Anthropic PDF, `~/Downloads`) → pitch insights committed to the playbook (`abdfcad`): founder-as-orchestrator narrative, problem-solution-fit framing, measurement framework, false-PMF honesty, devil's advocate prep.
5. **Mobile track started** (see below).

## Mobile track — where it stands
**Scope: FULL PARITY, NO CUTS** (Vasily 2026-06-19: «мобилка должна быть не менее полезна»). Plan: `docs/superpowers/plans/2026-06-19-mobile-to-market-week.md`.

- Flutter app, sound architecture (Riverpod, go_router, freezed, l10n RU/EN). 17 dart files. ~30% parity but functional.
- **DONE:**
  - #13 baseline — `flutter build apk --debug` works; runs on kali_test_34; **applicationId `com.example.kali_mobile`→`ai.kali.mobile`** (namespace kept to avoid MainActivity move). (`57ee9e9`)
  - #14 live `/dashboard` — backend computes real weather/tasks/spending, honest «—» not fake defaults; mobile fallbacks → «—». Verified at :3005. (`bad1aef`) **NOT yet visible on mobile until the in-flight backend rebuild + restage.**
  - **Emulator↔backend bridge PROVEN** — mobile connects + renders (dashboard, nav, UGC reel screen).
- **NEXT (priority order, nothing cut):**
  - #15 **Мастерская parity** — categories + honest statuses (`/agents/config-status`) + inline key entry + Мои/Витрина/Сообщество. `mobile/lib/presentation/agent_store_screen.dart` (15KB). Biggest UI port.
  - #16 **voice builder** — speak→create agent→deploy. Reuse backend `/builder/*` (works). THE wedge.
  - #18 kill dashboard mockups (hardcoded «Jarvis Insight» insightText + «agent ready» teaser in l10n).
  - #19 memory UI · #20 Canvas/Activity/Nightstand · #21 **Share-to-Reels real export**.
- **Honest timeline:** true full parity ≈ 2 weeks. In the week: land #13-16 (moat) well; #18-21 fast-follow. Sequenced, not dropped.

## The :3006 bridge recipe (CRITICAL infra — how to get mobile connected)
Mobile hits `ws/http://<ip>:3006`. From the emulator, host = `10.0.2.2`. To bring up :3006:
1. Stop any running backends + clear lock: `taskkill /F /IM kali-backend.exe; taskkill /F /IM kali-desktop.exe; del %APPDATA%\KALI\kali-backend.lock`
2. Run the staged desktop: `Start-Process dist_premium\premium_stage\kali-desktop.exe` → it serves :3006 (Rust embedded) + spawns :3005 (Python sidecar). Wait ~44s for both ports.
3. Emulator: tap «Подключиться» (IP prefilled 10.0.2.2). `adb shell input tap 540 1475`.
- **Caveat:** the staged desktop runs the FROZEN backend. To get LATEST source fixes onto mobile you must rebuild the frozen backend + restage first (the recurring loop). Running source Python :3005 alone does NOT serve :3006 (that's the Rust layer inside the Tauri app).
- Flutter/adb paths: `C:\src\flutter\flutter\bin\flutter.bat`, `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`, emulator `%LOCALAPPDATA%\Android\Sdk\emulator\emulator.exe -avd kali_test_34`.

## UGC publish architecture (Vasily asked) — DECIDED
Share-to-Reels is currently a MOCKUP (export = SnackBar only). For the real thing: **use the OS native share sheet** — generate the reel video locally → Android share intent / iOS share sheet → user posts to TikTok/Instagram/YouTube with their OWN account in their installed apps. **NO per-platform OAuth/API integration** (those need weeks of platform app-review; overkill, and off our anti-pivot turf). This is #21.

## Investor demo (in a few days, LIVE on PC)
- Desktop installer ready + verified. Playbook: `docs/demo/2026-06-15-investor-demo-playbook.md`.
- **Vasily's morning checklist** (in the playbook): reinstall, warm voice, 5-phrase mic pass (≥4/5), restart ×3, open all nav, create skill by voice → appears in «Мои».
- **Only Vasily can do the mic pass** (real device). That's the last unverified RED risk.

## Open / Vasily actions
- **Mic pass** on the fresh desktop install (5 phrases).
- **Create repo** `github.com/VasilyKolbenev/kali-skills` (Сообщество tab + publish flow need it; currently 404 → invite empty-state).
- **License plan** for CC-BY-NC F5 model before commercial launch (договор/своя/замена).
- Decide post-demo order: mobile parity vs desktop public-gaps (consent-gate, metrics, UGC).

## Gotchas (don't re-discover)
- **Subagents over-report** — VET every finding against real code (the false «keys leaked» alarm). Especially security BLOCKERs.
- **PowerShell + Cyrillic** → mangles; write JSON via `[IO.File]::WriteAllText($p,$s,[Text.UTF8Encoding]::new($false))` or use Python with `urllib`. Cyrillic literals in PS commands corrupt.
- **adb screenshots:** `adb shell screencap -p /sdcard/x.png` then `adb pull` — NOT `adb exec-out screencap -p > file` (PS `>` writes UTF-16, corrupts the PNG).
- **git commit messages via PS 5.1:** use `-F file` (UTF-8 no BOM), never `-m "...кириллица..."`.
- **Single-instance lock** (`%APPDATA%\KALI\kali-backend.lock`) blocks a 2nd backend BY DESIGN — kill backends + del lock before running a fresh one. A source backend can't co-run with the staged app.
- **Mobile namespace vs applicationId:** MainActivity.kt is in `com.example.kali_mobile`; namespace stays there, only applicationId changed (full package rename = MainActivity move, deferred).
- **Frozen backend = what mobile/desktop ACTUALLY run.** Source changes need a rebuild+restage to land. Verify at the level you claim.
- **ruff main.py** has a ~565-585 pre-existing noise floor; check count vs HEAD to confirm you added none, don't try to zero it.
- Emulator AVD = `kali_test_34` (API-34), NOT Pixel_7 (corrupt render — see memory).

## Verification scratch (gitignored)
- `verify_demo.py` (agent/chat/dashboard live checks), `verify_stt.py` (transcribe a WAV), `verify_builder.py` (full builder flow). Reusable; in .gitignore.

## Working principles (binding — carry forward)
- Plan-first gate on big work; generator→validator; verification = evidence (real playback/screenshot, not vibes); Russian-first, краткость; commit to main, DON'T push without ask; anti-pivot (no dev/design OAuth — native share sheet, not platform APIs).

*Resume: (1) check backend rebuild `bf3z01ox9`; if done, restage + relaunch staged desktop + confirm mobile shows live dashboard. (2) Start #15 Мастерская port with live emulator verification. (3) Investor demo prep stands on Vasily's mic pass. ~55+ commits local on main, unpushed.*
