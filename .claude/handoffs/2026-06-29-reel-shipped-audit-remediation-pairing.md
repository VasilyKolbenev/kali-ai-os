# Handoff 2026-06-29 — Reel shipped · 4-track audit · remediation plan (Option C) · P1.1 pairing done

> Continues from `.claude/handoffs/2026-06-28-launch-drive-ws1-ws5-marketplace-security-distribution.md`.
> **HEAD = origin/main = `2f4cb39`** — everything PUSHED (backup current). ultracode used for the audit. Anti-pivot CLEAN throughout.

## ЧИТАЙ В ЭТОМ ПОРЯДКЕ (до кода)
1. **Этот хэндофф** ← главный
2. `docs/public-launch/2026-06-29-launch-readiness-4track-audit.md` ← per-track readiness + strategy verdict
3. `docs/public-launch/2026-06-29-remediation-plan.md` ← **THE плана** (Option C, Phase 1 items, gates)
4. `docs/superpowers/specs/2026-06-29-ugc-reel-share-design.md` (+ `.ru.md`) + `docs/superpowers/specs/2026-06-29-mobile-pairing-token-design.md`
5. `memory/MEMORY.md` + `memory/project_core_loop_sprint.md` + `memory/project_competition.md`

## VERIFY STATE
```
git rev-parse --short HEAD                # 2f4cb39 (= origin/main, 0 ahead)
.venv\Scripts\python.exe -m pytest -m core_loop -q        # 13 passed
.venv\Scripts\python.exe -m pytest tests/reel -q          # 10 passed
cd src-tauri && cargo test --lib backend::auth            # 8 passed
cd mobile && "C:\src\flutter\flutter\bin\flutter.bat" test # ~28 passed (token_store, pair_link, share_to_reels…)
```

## ЗАКРЫТО ЭТУ СЕССИЮ (не переделывать — all pushed)
- **UGC voice-REEL feature** (merged `e3a7369`). Static PNG share-card → backend-rendered **9:16 MP4 where the agent speaks an auto-intro in its own voice** (the hook OpenHuman can't copy). `kernel/reel/` (intro→TTS→PyAV/**libopenh264** LGPL-safe→legible vendored DejaVuSans Cyrillic + word-wrap), `GET /skills/{name}/reel` (honest-fail JSON + mobile PNG fallback, content-type branch), PyInstaller bundling (av/PIL/qrcode/fonts). Full brainstorm→spec→plan→subagent-TDD→per-task+holistic review→reel-frame visually verified. core_loop 13 (was 10) + reel 10 + mobile 6.
- **4-track + strategy audit** (ultracode, 6 agents) → `docs/public-launch/2026-06-29-launch-readiness-4track-audit.md`. Verdicts: **Win 75% / iOS 60% / Android 35% / macOS 25%**, strategy **62% anti-pivot CLEAN**. The ONE deviation: gated Apple tracks were polished while ungated **WS-4.7 (mobile standalone) stayed unbuilt** → UGC "receive" half collapses on mobile.
- **Remediation plan + scope decision C** (Vasily) → `docs/public-launch/2026-06-29-remediation-plan.md`: ship v1 = **Windows desktop + desktop-tethered mobile companion** now; WS-4.7 = first fast-follow (v1.1).
- **P1.2 PARTIAL**: backend REBUILT (`uv run --with pyinstaller python scripts/build_backend_premium.py` → `dist_premium/kali-backend`, 5.61GB, exit 0). Verified `_internal/` now bundles `kernel/reel/assets/*.ttf` + `av.libs/{avcodec-62,avformat-62,swresample-6}.dll` + PIL + qrcode (the audit's "not bundled" finding is now FALSE at file level). **Runtime DLL-load + full reel render NOT yet verified (RTX live-verify remains).**
- **P1.1 tethered pairing-token** (merged `2f4cb39`, 5 commits + holistic review = ready-to-merge). Closes the audit Android 401/unreachable blocker. Mobile: `token_store.dart` (TokenStore/TokenHolder/KaliTokenInterceptor), Dio injects `X-KALI-Token`, ws appends `?token=`, `kali://pair?ip=&token=` deep-link (parse+persist+hold+connect) + startup hydration. Rust: `/ws` accepts `?token=` (only on /ws, constant-time, loopback exempt) + `GET /pairing/lan-ip` (loopback). Desktop UI: `PairPhone.tsx` QR view (`kali://pair`, bare IP — mobile appends :3006) + "Подключить телефон" in ModeSelector + honest "set `KALI_LAN=1` + restart" when LAN off. Tests: Rust 8 + Flutter 28 + UI 7.

## АКТИВНЫЕ ЗАДАЧИ (Phase 1, по приоритету — code-now)
1. **P1.3 — 8-agent SSRF: urllib → proxied `self.http_request`** (M). `agents/{weather,currency,news,github,telegram,todoist,notion,messenger-hub}/agent.py` still raw urllib (bypass SSRF/whitelist). github first (accepts full URL). Chip `task_52e8b474`. WS-2.8 already did monitor + web-surfer.
2. **P1.4 — GPLv3 FFmpeg resolution** (M+legal). 7 DLLs in `dist_premium/premium_stage/models/ffmpeg/` ship with NO license; avutil = GPLv3 + `--enable-gpl`/libx264 (desktop F5/torchcodec path, unrelated to reel's LGPL libopenh264). Options: LGPL rebuild / drop torchcodec FFmpeg dep / legal + NOTICE. **Public-release blocker.**
3. **P1.2 remaining — RTX live-verify**: boot the freshly-rebuilt `dist_premium/kali-backend/kali-backend.exe`, hit `GET /skills/{name}/reel` once (proves PyAV native DLL load + font path resolve at runtime — the audit's #1 risk, file-level done but not runtime), then a real create→works→share + two-device import. Vasily-driven on the RTX machine.
4. **P1.5 — honest tethered-UGC framing** (S, partly done: connection-screen QR hint added in P1.1). Remaining: landing copy (`docs/public-launch/index.html`).
5. **Phase 2: WS-4.7 mobile standalone-lite engine** (XL) — fast-follow after v1; its OWN brainstorm→spec→writing-plans→subagent cycle (see master plan WS-4.7 + `docs/public-launch/2026-06-19-mobile-standalone-design.md` if present).

## 🚧 GATES (Vasily, parallel — code is ready/mockable)
EV code-signing cert (**START NOW** — 1-3wk = critical path to public Windows) · owned domain (replaces parked kali.app) · CDN (~4.9GB resumable) · legal Privacy/EULA · Mac+Apple-Dev (entire iOS/macOS column, post-v1) · Play Console + upload keystore · GPLv3 FFmpeg decision (P1.4).

## ГОТЧИ (verified this session)
- **flutter NOT on PATH** → `C:\src\flutter\flutter\bin\flutter.bat` (run from `mobile/`).
- **`ui/` uses pnpm, NOT npm** (`npm install` crashes the pnpm tree) → `pnpm add` / `pnpm run build` / `npx vitest run`.
- venv uses **uv** (not pip) → `uv pip install` / `uv run`. `make` NOT installed → `.venv\Scripts\python.exe -m pytest`.
- **Rust LAN bind is STARTUP-ONLY** (`KALI_LAN=1`); no runtime rebind. Pairing view honestly prompts to set env + restart.
- Frozen backend rebuilt at `dist_premium/kali-backend` (5.61GB) but **NOT live-verified** + the full installer (tauri + `build_installer_premium.bat`) was NOT produced (Vasily: no point building at current readiness). Rebuild seq if needed: `uv run --with pyinstaller python scripts/build_backend_premium.py` → `npm --prefix ui exec -- tauri build` → `build_installer_premium.bat` (robocopy `/E` not `/MIR`).
- mobile pairing QR encodes **bare IP** (no :3006) — mobile `ServerConfig.port` appends it.
- Pre-existing: ~11 mobile analyze infos in untouched files; native segfault at teardown of FULL tests/e2e run (test_full_flow Silero, unrelated).

## ПРИНЦИПЫ (binding)
plan-first + brainstorm HARD-GATE · generator→validator · subagent-driven TDD (fresh agent/task + spec-then-quality review) · verification=evidence (real tests/live frame, not mocks) · качество>скорость · live-verify in REACHABLE views · anti-pivot (voice creation + mobile + UGC + local data; NO dev integrations / 118-breadth / OS-assistant / crypto-market; magic-link NOT OAuth; token = LAN-local security not identity) · русский/кратко · commits on main + ПУШИТЬ (backup) · пауза после флоу.

## НАЧНИ С
verify-state + этот хэндофф + remediation-plan → **P1.3 (SSRF 8 agents, github first)** or **P1.4 (GPLv3 FFmpeg decision — ask Vasily: rebuild LGPL vs drop torchcodec vs legal)**. Vasily should kick off **EV-cert** now (long pole). **Prior:** `2026-06-28-launch-drive-ws1-ws5-marketplace-security-distribution.md`.
