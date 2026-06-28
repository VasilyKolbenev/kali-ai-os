# Handoff 2026-06-28 — Launch drive: WS-1..WS-5 executed (core-loop locked · marketplace B/C built · security hardened · distribution ready)

> Continues from `.claude/handoffs/2026-06-25-coreloop-10fixes-rebuild-push-marketplace-spec.md`.
> **36 commits this session (since `5d7195b`). HEAD = origin/main = `6b4dcfe`** — everything PUSHED (backup current). ultracode ON throughout.

## ЧИТАЙ В ЭТОМ ПОРЯДКЕ (до кода)
1. **Этот хэндофф** ← главный
2. **`docs/public-launch/2026-06-26-launch-readiness-master-plan.md`** ← THE source of truth (5 workstreams, every task, status). Almost all of it is now DONE — this handoff says what's left.
3. `C:\Users\User\.claude\projects\C--Users-User-Desktop-Jarvis\memory\MEMORY.md` (+ `memory/project_core_loop_sprint.md`)
4. `docs/superpowers/specs/2026-06-25-kali-community-marketplace-design.md` (marketplace A/B/C — A+B+C now built against mock Supabase)
5. `docs/public-launch/2026-06-24-prod-readiness-audit.md` (the original audit; most blockers/highs now addressed — see ЗАКРЫТО)

## VERIFY STATE
```
git log --oneline -1            # = 6b4dcfe
git rev-parse --short origin/main  # = 6b4dcfe (0 ahead — all pushed)
git rev-list --count 5d7195b..HEAD # = 36
.venv\Scripts\python.exe -m pytest -m core_loop -q   # = 10 passed (the core-loop gate; `make` not installed → use venv python)
```
NOTE: WS-1 commit SHAs were REWRITTEN by a `git filter-branch` (see ГОТЧИ — workflow-scope push-block); reference WS-1 by the `-m core_loop` gate, not by SHA. WS-2..WS-5 SHAs (below) are stable.

## КОНТЕКСТ (session arc)
Start: Phase A (marketplace P2P share) was done+pushed (`d2fcb29`). Vasily approved the **master launch plan** (5-assessor + synthesis Workflow → `docs/public-launch/2026-06-26-launch-readiness-master-plan.md`) and said **«всё нужно, без остановок»** (finish the whole product across all platforms). Executed **WS-1 → WS-5** via subagent-driven TDD (every task: ground → dispatch implementer → calibrated review → accept; full adversarial review for security/logic, lighter for contained/test-only). Hard gates (EV cert, domain, Supabase, Mac+Apple-Dev, Play/App-Store accounts) — Vasily started ALL of them in parallel. Stopped for the night with 2 tasks left (2.6a + the XL 4.7) + low context.

## ЗАКРЫТО ЭТУ СЕССИЮ (не переделывать — all pushed)

### WS-1 — Core-loop e2e harness ✅ (loop LOCKED, SHAs rewritten by filter-branch)
`pytest -m core_loop` = **10 real-component tests** (not MagicMock) proving: build→deploy→cron→callable→dispatch (keystone) · schedule→fire→notify · voice-executes-tool (BOTH pipelines, mutation-verified) · share-roundtrip + honest-fail-on-non-spec-name · onboarding-deploys-only-after-deploy · local-provider forwards/parses tools. Converts the spine sprint from "claimed" to "PROVEN fixed". Gate wired: `make test-core-loop` + pre-push hook + `ci/core-loop.yml` (staged in `ci/`, re-home to `.github/workflows/` via UI). Also fixed 6 stale `anthropic`-patch tests (green baseline).

### WS-2 — Security/trust hardening (9/10 + 2.8 done; 2.6a remains)
- **2.1 M2.1 declaration-scoped permission** (`731bd4b`,`9caac52`) — the TRUST LAUNCH-BLOCKER. `can_execute` deny-by-default for destructive actions (verb classifier); destructive allowed only if in agent's declared `capabilities` + user_approved; `runtime.py` now passes `execute:{action}` (voice/chat path covered). Branch-(a) over-grant tightened (read-only caps no longer authorize destructive). 18 bundled agents audited — none newly denied. Branch-(b) access-class granularity documented as intentional.
- **2.2 Rust :3006 token+bind** (`266e3d9`) — closes audit BLOCKER. bind default 127.0.0.1 (LAN opt-in `KALI_LAN=1`), per-install 256-bit CSPRNG token, `auth::require_token` middleware (loopback exempt → webview frictionless, LAN requires Bearer/X-KALI-Token). cargo: 80+7 tests green. Mobile token-presentation/pairing = DEFERRED to mobile-transport (seam `GET /pairing/token` exists).
- **2.3 trademark scrub** (`b0ee72f`) — Marvel "Iron Man/Tony Stark" strings removed from BOTH ElevenLabs payloads (`tts_engine_elevenlabs.py` + `tools/elevenlabs_recreate_clone.py`).
- **2.4 Python safe-by-default** (`782f955`) — host default 127.0.0.1, CORS scoped to real Tauri/Vite origins (no `*`+credentials), `test_cors.py`.
- **2.5 LLM-picker** (`5cfe1cf`) — now PATCHes `{llm:{cloud_provider,cloud_model}}` via crash-safe config path → router actually switches (was env-only, inert).
- **2.6b + 2.9 notifier honesty** (`209d565`) — `notify_channel` honored; telegram delivers via `agents/telegram` when configured else honest `unconfigured`/`error` (never fake `sent`); RoutineManager `executed`→`published`.
- **2.7 runtime is_loaded/ensure_loaded** (`1e23276`) — dead agents re-spawn instead of confusing "not loaded".
- **2.8 SSRF egress** (`6b4dcfe`) — monitor template + web-surfer `--url` (third-party-reachable) routed through SSRF-guarded `SandboxHttpClient` (private IPs blocked even if whitelisted); smart-home already safe.
- **2.10 key-fragment scrub** (`b0ee72f`) — `…DFMA`/`sk-proj-…` removed from tracked docs.

### WS-3 — Marketplace B/C ✅ FULLY BUILT against mock Supabase (9/9)
- **3.1 schema+RLS** (`0f2f5ba`) — `supabase/migrations/*.sql`: 7 §4 tables + 24 RLS policies (anon likes/installs · authed ratings/comments · creator-scoped skills · flags moderation-only · UPDATE+SELECT pairs · `(select auth.uid())` · NO `user_metadata` authz) + `trending_skills` view (`security_invoker`). sqlfluff-parse clean.
- **3.2 CatalogClient §4** (`85a472d`) — rewrote prototype: search/browse/trending/publish/creator-CRUD/record_install, supabase-py lazy + graceful degradation.
- **3.3 identity** (`03227fe`) — device-id (anon) + magic-link KALI account (NOT OAuth); publish honestly requires sign-in.
- **3.4 social** (`ff0234c`) — like(device,1/dev)/rate(account,1/user)/comment + `/catalog` routes; honest sign-in-required passthrough.
- **3.5 «Сообщество» reconcile+UI** (`57a2b46`) — `/catalog/community` merges Supabase-UGC ∪ GitHub-curated (dedup); cards get like/rate/comment + `MagicLinkDialog` (email OTP, no OAuth); graceful degrade to curated when Supabase offline. 135 vitest + tsc clean.
- **3.6 .kali-agent zip** (`b3ddbad`) — Phase B catalog format now carries voice skills (synth SKILL.md reused from Phase A), `register_dir`-callable; CatalogClient publish/install wired; zip-slip preserved.
- **3.7 moderation** (`fce87aa`) — `content_gate.scan_prose` (prompt-injection heuristic) + `auto_approve_gate` (AST+prose, both required; **§5C: script-less malicious prose → pending, NOT auto-approved**); report (public) + transitions (admin `_require_moderator`, closed-by-default 403).
- **3.8 legacy cleanup** (`8278028`) — none needed (3.2 already removed flat-`packages`); doc updated.
- **3.9 share-card PNG** (`b953e8f`) — Flutter RepaintBoundary→PNG agent card to native share; `flutter analyze` clean + 3 widget tests.

### WS-4 — Platform configs ✅ (4.1-4.6 + 2.2; 4.7 XL remains)
- **4.1-4.6** (`109e5c5`) — iOS Info.plist (mic + `kali://` scheme), `ai.kali.mobile` across iOS/macOS, macOS entitlements (audio-input + network.client), Android namespace moved + label KALI + netsec config + release signingConfig (keystore.properties seam), base-URL centralized in `mobile/lib/core/config.dart`. `flutter analyze` clean. **Concern:** Android `<domain>` can't express RFC1918 CIDR → base-cleartext LAN-only documented (full fix = HTTPS relay). Mac/device build+sign verify DEFERRED (needs Mac).

### WS-5 — Distribution ✅ (8/8, build-verify deferred to next rebuild)
- **5.1-5.4** (`1ea0527`) — DiskSpanning→single `.exe`, signtool subroutine (env-gated, no-op w/o cert), fail-fast `robocopy /E` staging, dead `ggml-base.bin` (148MB) deleted. **Silero KEPT (3 distinct live files** — Rust ort VAD / faster-whisper / OpenWakeWord — audit's "dedupe" premise was stale).
- **5.5-5.6** (`edf8404`) — inert/unowned-host updater block removed; `bundle.targets ["msi"]→[]`; `installer_lite.nsi` retired (orphaned).
- **5.7** (`00df4fa`) — landing OS-detect + `kali://import` deferred-install redirector; canonical deep-link = https-primary (`/import?n=&d=`), kali:// fallback, **parity preserved** (P2P loop untouched); `.well-known/assetlinks+aasa` + `_redirects` templates.
- **5.8** (`af42b51`) — CI/fastlane scaffolding (`ci/release-desktop.yml`, Android/iOS fastlane + `ci/mobile-*.yml`), all in `ci/` (push-safe), secrets-gated manual dispatch.

## АКТИВНЫЕ ЗАДАЧИ (по приоритету)
1. **WS-2.6a — voice-TTS on schedule** (interrupted mid-dispatch). When a scheduled skill fires with channel "голос/voice", SPEAK it via the idiomatic TTS seam (likely an EventBus `voice.speak`-style event the pipeline plays — GROUND `_on_skill_trigger` in `kernel/main.py:460-499` + how `kernel/voice/pipeline.py` emits TTS). Honest fallback to notification. ML-free test (mock the TTS sink). Extend `tests/e2e/test_core_loop_schedule_fire.py`.
2. **WS-4.7 — mobile on-device-lite engine (XL)** — the BIG remaining piece + the real mobile 1.0 cost. A Dart orchestration spine making the mobile app STANDALONE (chat via cloud LLM, template skills, builder, dashboard, local SQLite, on-device bundle import) so a desktop-less friend can use it — closes the UGC loop. **NOT porting ML to phone.** This deserves its OWN writing-plans → subagent-driven cycle (a fresh focused session). See master plan WS-4.7 + `docs/public-launch/2026-06-19-mobile-standalone-design.md` if present.
3. **Critique defaults not yet done** (lower-priority): honest-success sweep is mostly done (2.6b); `schedule.morning/evening` briefing subscriber still unimplemented (feature, deferred as not-hardening).
4. **8-agent SSRF follow-up** — chip spawned (`task_52e8b474`): migrate weather/currency/news/github/telegram/todoist/notion/messenger-hub from raw urllib → proxied `self.http_request` (github first — accepts full URL). First-party, lower-risk.
5. **Live-verify pass** (before public rollout) — rebuild installer (carries ALL session fixes; current 4.2GB installer is STALE, pre-this-session) → Vasily live-tests the loop + two-device share. Plus iOS/macOS build+sign (needs Mac), Android signed AAB (needs keystore).
6. **Push 2.6a + the 8-agent fix** when done (by Vasily's word — pattern is commit-on-main + push for backup).

## 🚧 HARD GATES (Vasily started ALL in parallel — code is ready/mockable for each)
- **EV code-signing cert** (1-3wk lead = critical path to Windows public) — signtool pipeline commits inert, signs once `KALI_SIGN_CERT` env set.
- **Registered domain** (kali.app unowned) — unblocks updater + CDN + landing-live + Android App Links (assetlinks.json) + iOS Universal Links (AASA). Set `ShareConfig.linkBase` + `window.KALI_DIST.linkBase` + the `{{*_URL}}` placeholders in `index.html`.
- **Provisioned Supabase project** — apply `supabase/migrations/*.sql` then **MANDATORY `supabase db advisors`** (the RLS verification gate — was static-validated only). Set the Supabase env so `CatalogClient` goes live.
- **Mac + Apple Developer ($99/yr)** — the entire iOS/macOS column (build/sign/notarize/TestFlight). Configs ready; Team ID into AASA + fastlane.
- **Android upload keystore + Play Console** — `keystore.properties` + `PLAY_SERVICE_ACCOUNT_JSON`.
- **Cloud host/CDN** for the ~4.9GB installer + the mobile relay (4.7 alternative).
- Smaller: rotate the OpenAI key (`…DFMA`); Telegram bot token (notifier live delivery); legal Privacy/EULA review.

## ГОТЧИ (verified this session)
- **`workflow`-scope push-block:** the push token can't add files under `.github/workflows/`. The 1.6 commit added `core-loop.yml` there → push rejected → resolved by `git filter-branch` stripping it from history + staging it under `ci/core-loop.yml`. **ALL CI workflows now live in `ci/`** (`core-loop.yml`, `release-desktop.yml`, `mobile-android.yml`, `mobile-ios.yml`) — Vasily re-homes them to `.github/workflows/` via the GitHub web UI (or pushes with a `workflow`-scoped token). Future: don't commit under `.github/workflows/`.
- **`make` NOT installed** on Vasily's Windows box → use `.venv\Scripts\python.exe -m pytest -m core_loop`.
- **ruff/mypy NOT in `.venv`** → implementers ran them via `uvx ruff` / left lint to CI. ~200 pre-existing ruff findings (legacy debt; CI ruff = informational).
- **Pre-existing test failures (NOT regressions, confirmed on clean HEAD):** ~11 `tests/kernel/sandbox/test_http_client.py` (captive-DNS resolves public hosts as private in this env); `test_plugin_registry_dual::test_tools_namespaced_correctly` (stale: asserts len==1 but built-in `kali__list_my_agents` makes it 2 — chip `task_e7bd03fb`); 6 builder-generator tests need API keys; a native segfault at teardown of the FULL `tests/e2e` run (from `test_full_flow.py` Silero/live-canvas).
- **No live Supabase/Mac here** → WS-3 mock-tested, WS-4 iOS/macOS config-only. Verification deferred to the provisioned gates (advisors / Xcode build).
- **Installer is STALE** (4.2GB from a prior session) — a rebuild is needed for ANY of this session's fixes to run live. Rebuild seq (from prior handoff, verified): `uv run --with pyinstaller python scripts/build_backend_premium.py` → `npm --prefix ui exec -- tauri build --no-bundle` → the now-SCRIPTED staging in `build_installer_premium.bat` (5.3, `robocopy /E` not `/MIR`) → `cmd //c scripts\build_installer_premium.bat`. The Rust `:3006` token + bind-127.0.0.1 only take effect after rebuild+restart (a stale backend may still be bound 0.0.0.0).
- Calibrated review (this session's rhythm): full adversarial review for security/logic (M2.1, Rust token); combined/lighter for contained config + test-only.

## ПРИНЦИПЫ (binding)
ultracode ON · plan-first + brainstorm HARD-GATE · generator→validator · verification=evidence (real test/live run) · качество>скорость · live-verify UI in reachable views · вето находки/ROADMAP против кода · русский/кратко · пауза после флоу · commits on main + ПУШИТЬ (backup) · anti-pivot (native share + `kali://`/https deep links, local data = moat, KALI magic-link account NOT per-platform OAuth, self-declared social handles = display strings).

## НАЧНИ С
verify-state + этот хэндофф + master plan → спроси Vasily приоритет: **(а) 2.6a voice-TTS** (быстрый, доделать), **(б) 4.7 mobile on-device engine** (XL — нужен свой writing-plans цикл; это главный remaining), **(в) live-verify** (rebuild installer → тест loop+share), или **(г)** триаж гейтов по мере их закрытия (Supabase apply+advisors, domain wiring, signing). ultracode ON. Всё запушено (`6b4dcfe`). **Prior:** `2026-06-25-coreloop-10fixes-rebuild-push-marketplace-spec.md`.
