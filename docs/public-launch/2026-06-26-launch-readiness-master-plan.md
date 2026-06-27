# KALI — MASTER LAUNCH PLAN (consolidated 2026-06-26)

Source: 5 grounded assessments (core-loop, marketplace B/C, prod-hardening, platform matrix, distribution), spot-verified against current code on `main` @ `5d7195b`.

---

## 1. Verdict

KALI's **core voice loop is now wired correctly in code** — the spine sprint + Marketplace Phase A genuinely closed all 5 blockers and most HIGHs from the 25-Jun critique (verified: `tool_dispatch.py`, `_on_skill_trigger` at main.py:499, `register_dir`, export fallback, local-provider tool forwarding). But it **rests entirely on faith**: nothing is live-verified, the only e2e test uses a `MagicMock` executor and asserts files-on-disk only, and 6 `agent_generator` tests are red. On distribution, **only Windows desktop is shippable-shaped, and even it cannot go public** — zero code-signing (confirmed: no `signtool` anywhere), a DiskSpanning 4-file installer footgun, an inert updater pointing at an unowned domain, and a Rust control plane on `0.0.0.0:3006` with no auth. Android/iOS/macOS are all blocked on a missing standalone backend (the mobile app is a thin LAN client that dies at the connection screen with no nearby desktop), plus per-platform human-gates.

**The single biggest risk:** the loop is *claimed* fixed but *unproven*, and the open M2.1 permission fall-open became **more dangerous the moment blocker #1 closed** — voice/chat now execute real destructive actions (calendar.delete, email/telegram send) behind a single implicit approval. Lock the loop with real-component e2e tests **before** any feature work; treat M2.1 as a launch blocker for the trust loop.

---

## 2. What I (the coding agent) can complete autonomously NOW

This is the bulk of the executable plan. All items below are `code-now` or `code-mockable` — no external accounts/hardware required. Grouped into 5 workstreams.

### WS-1 — Core-loop e2e test harness (HIGHEST LEVERAGE — do first)
Converts the spine sprint from "claimed fixed" to "proven fixed." All tests stub STT+LLM+TTS so they run in CI without torch/F5/whisper; reuse the existing `ASGITransport` harness but **swap the `MagicMock` executor for a REAL `SkillExecutor`**.

| # | Task | Effort | Key files |
|---|------|--------|-----------|
| 1.1 | **Fix the 6 red `agent_generator` tests first** (green baseline). `patch('kernel.builder.agent_generator.anthropic', …)` is stale — module-level import moved inside the function. Restore module-level import OR repoint the patch. | S | `tests/test_builder_generators.py:205-368`, `kernel/builder/agent_generator.py` |
| 1.2 | **VERIFY-1 (keystone): build→deploy→callable e2e.** Drive `/builder/start`→answer×N→deploy with a REAL `SkillExecutor` + `PluginRegistry` on tmp `agents_dir`. Assert (a) `skill.yaml` has `reminders.interval_hours` from "каждые 2 часа", (b) `register_cron` called with topic `skill.{name}.trigger`, (c) `get_all_tools()` contains the deployed skill's namespaced tool (`{name}__check` for the reminder template; `__log` is the tracker template), (d) `execute_tool_call` dispatches and returns a real result. Replaces the file-only `MagicMock` e2e. | M | NEW `tests/e2e/test_core_loop_build_deploy.py`; exercises `builder/flow.py`, `deployer.py`, `skill_generator.py`, `plugin_registry.py` |
| 1.3 | **VERIFY-2: schedule→fire→notify e2e.** Publish `Event(topic='skill.{name}.trigger')` on the real `EventBus` (bypass wall clock); assert `NotificationManager.send` invoked with the message and `should_fire=False` suppresses. Pin template→action map (`{reminder:check,…}`). + unit test asserting `register_cron` emits `skill.{name}.trigger` (not `schedule.cron.{name}`). | M | NEW `tests/e2e/test_core_loop_schedule_fire.py`; `kernel/main.py:460-499`, `scheduler.py` |
| 1.4 | **VERIFY-3: export→import→callable round-trip e2e.** Voice-build (manifest+skill.yaml, no SKILL.md) → `GET /skills/{name}/export` → feed base64 to `POST /skills/install-bundle` in a SECOND registry → assert parses through strict SKILL.md loader, registered, in `get_all_tools()`, dispatches. Assert Cyrillic-named export returns honest error, not a dead bundle. | M | NEW `tests/e2e/test_core_loop_share_roundtrip.py`; `main.py:2069-2167`, `publisher.py`, `installer.py` |
| 1.5 | **VERIFY-4: onboarding + voice/local dispatch tests.** (a) Update `FirstAgentStep.test.tsx` to assert `builderApi.deploy` is called when `extract` returns `complete:true` and success copy appears ONLY after deploy. (b) Python test: drive `_handle_transcription` with stubbed LLM returning a tool_call, assert `execute_tool_call` ran and spoken `final_text` reflects the result (both pipelines). (c) `llm_router` test with mock Ollama (httpx) asserting `available_tools` forwarded and `tool_calls` parsed back. | M | `ui/.../FirstAgentStep.test.tsx`; NEW `tests/test_voice_tool_dispatch.py`; `llm_router.py:374-421` |
| 1.6 | **VERIFY-6: CI gate.** Mark VERIFY-1..4 as a fast ML-free suite; wire into `make test` / pre-push so the loop re-verifies on every change. Keep under a few seconds. Gate heavy on-device F5/STT checks separately (manual/nightly). | S | `Makefile`, pytest markers, `.github/workflows/*` (none exist yet — create) |

### WS-2 — Trust & security hardening (several are real launch blockers)
The fast wins here are <1 day total. M2.1 is the trust blocker.

| # | Task | Effort | Key files |
|---|------|--------|-----------|
| 2.1 | **M2.1 — close the permission fall-open (LAUNCH BLOCKER for trust).** `METHOD_PERMISSIONS` has no `execute` key → `can_execute` returns True when `required is None`, so `execute:{action}` is unmapped and auto-authorized incl. destructive verbs. Add explicit execute-permission mapping, **deny-by-default for destructive verbs** (calendar.delete/email/telegram send), + tests. | M | `kernel/sandbox/permission_enforcer.py:10-63`, `backend.py:~147`, `runtime.py:~122` |
| 2.2 | **Rust `:3006` per-install bearer/pairing token (TOP security code-now item).** CORS is locked but irrelevant to the non-browser mobile client / LAN curl. Generate token on first run → store in `runtime_data_dir` → inject into Tauri webview + require mobile app to present it; enforce via axum middleware on mutating routes. OR make `RUST_BIND_ADDR` env-driven, default `127.0.0.1`, flip to `0.0.0.0` only when pairing enabled. Build+test fully local. | M | `src-tauri/src/backend/mod.rs:28,87`, `http/` router, `lib.rs:18` |
| 2.3 | **ElevenLabs trademark scrub (fast).** `name="JARVIS_KALI"`, `description="<Marvel-trademark voice description, redacted>"` → neutral `name="KALI_voice"`, `description="KALI assistant voice"`. (Confirmed still present.) | S | `kernel/voice/tts_engine_elevenlabs.py:197-198` (+ refs at 4/26/36) |
| 2.4 | **Python safe-by-default (defense-in-depth).** Shipped desktop is safe (Tauri injects `KALI_HOST=127.0.0.1`+locked CORS), but in-code defaults are still `0.0.0.0` + `["*"]`+credentials. Default host → `127.0.0.1`; `_DEFAULT_CORS_ORIGINS` → Tauri/Vite origin list; never combine `"*"` with `allow_credentials`. | S | `kernel/main.py:54-56,654-655,2390` |
| 2.5 | **Fix the LLM provider/model picker (loop-material).** `POST /settings` writes env+`.env`, but router reads provider/model from YAML (`config_manager.config.llm`) → switching OpenAI→Anthropic shows "Сохранено" but keeps old brain even after restart. Route the picker through the validated `PATCH /config` path (like `VoiceSettings` already does). | M | `kernel/main.py:2313-2368,1426`, `llm_router.py` |
| 2.6 | **Scheduled-skill TTS + honest-status sweep.** (a) Add TTS playback in `_on_skill_trigger` for the `voice` channel (wizard offers "голосом" but it only Notifications today); implement the `schedule.morning/evening` briefing subscriber (emitted, no consumer). (b) Sweep `notifier`/`RoutineManager` so no green `status:'sent'`/`'executed'` outlives a real no-op. | M | `kernel/main.py:460-499`, `scheduler.py:147-157`, `briefing.py`, `routines.py`, `skill_templates/notifier.py` |
| 2.7 | **`runtime.is_loaded()/ensure_loaded()`.** Dispatcher reaches into `runtime._agents` private state; a crashed subprocess stays in the dict and raises a confusing "closed stdout". Add a public check that also consults `protocol.is_running` and re-spawns if dead. | S | `kernel/agent_runtime/dispatcher.py:36-38`, `runtime.py`, `protocols/native.py` |
| 2.8 | **Route bundled agents through the network proxy.** The proxy now works (`native.py:149` invokes `NetworkProxy.handle`), but every bundled agent still calls `urllib.request.urlopen` directly, bypassing the whitelist/SSRF/rate-limit. Migrate bundled agents to the SDK `network.request` helper (or block raw socket egress). **Most under-appreciated gap for a user-generated-agent launch.** | M | `agents/{weather,github,telegram,…}/agent.py`, `protocols/native.py:147-160` |
| 2.9 | **Notifier telegram channel.** `_notify` only appends to `history.json` and returns `status:'sent'` — imports no Telegram client, and reads wrong key (`default_channel` vs wizard's `notify_channel`). Wire telegram to `agents/telegram` keyed on `notify_channel`, OR drop the channel from the wizard. Code + mock-delivery test land now; **live needs a bot token (human-gate).** | M | `kernel/skill_templates/notifier.py:50-81`, `wizard.py:82,97` |
| 2.10 | **Scrub committed OpenAI key fragment (`…<redacted>`)** from 3 tracked docs (the rotation itself is a human-gate). | S | `docs/handoffs/2026-05-18-*.md`, `.claude/handoffs/2026-04-22-*.md` |

### WS-3 — Marketplace B + C against a MOCK Supabase
**Phase A (P2P share→friend) is DONE — do NOT re-do it** (verified in `publisher.py`/`plugin_registry.py`/`main.py`/mobile). All below build/test against the `MagicMock` Supabase chain that already exists in `tests/test_catalog_client.py`; live wiring is human-gated.

> **Stale-doc correction (binding):** the existing `kernel/catalog/client.py` is the 2026-04-13 prototype on a single flat `packages` table (confirmed). This is **incompatible** with marketplace spec §4 (7-table creators/skills/ratings/likes/comments/flags/installs). Treat it as a prototype to be **rewritten**, not extended; its current tests will break and must be rewritten too.

| # | Task | Effort | Key files |
|---|------|--------|-----------|
| 3.1 | **Author Supabase schema as committed SQL migrations + RLS.** §4 DDL (7 tables, uniqueness constraints, `status` enum pending\|approved\|flagged\|removed), RLS policies (anon read approved; authed write own ratings/likes/comments; creator edits own skill), trending view = f(installs, likes, ratings, recency). No `supabase/` dir exists yet (confirmed). RLS is the spec's first line of moderation. Testable against local `supabase start`; needs a real project only to APPLY. | M | NEW `supabase/migrations/0001_catalog.sql`, `0002_rls.sql`, `0003_trending.sql` |
| 3.2 | **Rewrite `CatalogClient` to the §4 model.** Target `skills` (not `packages`); add creator-profile CRUD (handle + self-declared socials as **display strings only**), publish-skill (insert `status=pending` + Storage upload of `.kali-agent` bundle), browse/search/trending over `status=approved`, install attribution. **Keep the graceful-degradation contract** (return `[]`/`{}` when unconfigured). | L | `kernel/catalog/client.py`, `tests/test_catalog_client.py` |
| 3.3 | **Device-id + magic-link identity (client side).** Stable local device-id generator+store; `CatalogClient` upgrade to magic-link session (Supabase anon-auth → email magic-link); pass device-id to likes vs account to ratings/comments per §4 uniqueness. **Anti-pivot: KALI's own account, NOT Google/Apple OAuth.** | M | NEW `kernel/catalog/identity.py`, `client.py`, mobile + ui surfaces |
| 3.4 | **Phase C social layer (mock).** `CatalogClient` methods like/unlike, set_rating (1-5), post_comment, list_comments honoring uniqueness; backend routes; UI affordances on community cards (currently install-only). | L | `kernel/catalog/client.py`, `main.py` (new `/catalog` social routes), `ui/.../AgentStore/*` |
| 3.5 | **Reconcile the two parallel catalog stacks.** «Сообщество» uses the WRONG one — it fetches GitHub `SkillsCatalog` via `skillsCatalogList("kali")`; the Supabase `CatalogClient` is never called. Build a backend route merging Supabase `approved` UGC ∪ GitHub curated (dedupe); point `CommunitySection` at it; preserve the existing empty-state degradation. | M | `kernel/main.py`, `ui/.../AgentStore.tsx`, `CuratedStore.tsx`, `endpoints.ts` |
| 3.6 | **Wire `.kali-agent` zip as Phase B canonical format.** Pack/unpack + zip-slip protection already exist. Two gaps: (a) `installer.py` only AST-gates `agent.py` + deploys via `skill_yaml` — align it with publisher's SKILL.md-synthesis path so a voice-built skill packed as `.kali-agent` loads; (b) wire into new `CatalogClient.publish`(upload)/install(download→unpack). | S | `kernel/catalog/package.py`, `installer.py`, tests |
| 3.7 | **Moderation lifecycle (mock).** Status machine (pending→approved/flagged→removed), report button writing `flags`, hide flagged pending review. **CRITICAL §5C caveat the code must honor:** the AST gate scans `scripts/*.py` ONLY — most voice skills are script-less Markdown whose SKILL.md body is injected into the LLM prompt, so auto-approve **cannot rely on AST-pass alone**; prose review (prompt-injection) is required. Code mockable; go-live + review operation are human-gates. | L | `kernel/catalog/client.py`, `publisher.py` (`_scan_scripts_safety`), `main.py` |
| 3.8 | **Decide the fate of the legacy `/catalog/*` routes + flat `packages` table** (fold into the rewritten client or delete) to avoid two divergent catalogs at launch. | S | `kernel/main.py`, `kernel/catalog/*` |
| 3.9 | **Share-to-reels agent-card PNG.** §5B wants a rendered card (`RepaintBoundary→PNG`) shared to the native sheet; current screen shares text + inline QR only. Pure Flutter, testable on `kali_test_34` emulator. Improves the UGC hook. | M | `mobile/lib/presentation/share_to_reels_screen.dart` |

### WS-4 — Platform config edits (all code-now; land NOW so builds are clean when human-gates clear)
None of these were closed by the spine sprint (they live in mobile/Tauri config, not kernel) — all re-verified OPEN.

| # | Task | Effort | Key files |
|---|------|--------|-----------|
| 4.1 | **iOS Info.plist (3 edits — blocker for iOS surface).** Add `NSMicrophoneUsageDescription` (+`NSSpeechRecognitionUsageDescription` if on-device STT) with RU/EN purpose string — without it iOS SIGABRTs on first record + App Review auto-rejects. Add `CFBundleURLTypes` w/ `CFBundleURLSchemes=['kali']` — `kali://` import is 100% dead on iPhone today. (Confirmed both absent.) | S | `mobile/ios/Runner/Info.plist` |
| 4.2 | **iOS bundle id.** `PRODUCT_BUNDLE_IDENTIFIER` `com.example.kaliMobile` ×6 → `ai.kali.mobile` (+`.RunnerTests`). Apple rejects `com.example`. | S | `mobile/ios/Runner.xcodeproj/project.pbxproj:385,401,418,433,564,586` |
| 4.3 | **macOS config (Flutter light client = the 1.0 Mac path).** Set bundle id `ai.kali.mobile` + fix `com.example` copyright; add `NSMicrophoneUsageDescription`; **add MISSING entitlements `com.apple.security.device.audio-input` AND `com.apple.security.network.client`** (app-sandboxed Mac app can't record or make outbound calls without these — would silently fail post-compile); add `CFBundleURLTypes`. | S | `mobile/macos/Runner/Configs/AppInfo.xcconfig`, `Info.plist`, `Release.entitlements`, `DebugProfile.entitlements` |
| 4.4 | **Android namespace + label + cleartext scoping.** `namespace com.example.kali_mobile` → `ai.kali.mobile` (requires moving MainActivity Kotlin package); `android:label "kali_mobile"` → "KALI"; replace app-wide `usesCleartextTraffic=true` with a `networkSecurityConfig` whitelisting only RFC1918 LAN ranges (full removal waits on cloud/relay). (`applicationId` already `ai.kali.mobile` — good.) | M | `mobile/android/app/build.gradle.kts:11`, `AndroidManifest.xml:5,7` |
| 4.5 | **Android `signingConfigs.release` wiring** reading from gitignored `keystore.properties`/env, point release buildType at it — testable against a throwaway local keystore. (Real upload keystore is a human-gate.) Confirmed still `signingConfigs.getByName("debug")`. | S | `mobile/android/app/build.gradle.kts:30-34` |
| 4.6 | **Mobile base-URL centralization (prereq for the on-device/relay switch).** Chat/agent_store/settings/dashboard all hardcode `http://$ip:3006`. Centralize so LAN vs cloud is one switch. | S | `mobile/lib/core/http_client.dart:20`, `websocket_client.dart:34`, `deep_link_service.dart:74` |
| 4.7 | **Mobile on-device-lite engine (Option B — the REAL mobile 1.0 cost).** Ship a Dart orchestration spine: chat via cloud LLM, template skills, builder, dashboard, local SQLite, on-device bundle import. Makes "data stays on your phone" literally true and closes the P2P loop standalone. **NOT porting ML to the phone.** Buildable+testable now (live verify on iOS needs a Mac). | XL | `mobile/lib/` (new engine); `docs/public-launch/2026-06-19-mobile-standalone-design.md` |

### WS-5 — Distribution: single-file installer + signing-ready + updater wiring
> **Stale findings — do NOT re-raise (confirmed CLOSED):** HF-symlink trap fixed (`materialize_hf_symlinks.py` wired into `build_installer_premium.bat:37-48`); version skew fixed (`Cargo.toml` now `0.2.0-beta`); stale NSIS premium pipeline deleted (only `installer_lite.nsi` remains).

| # | Task | Effort | Key files |
|---|------|--------|-----------|
| 5.1 | **Collapse DiskSpanning → single signed `.exe`.** `DiskSpanning=yes` + 2.1GB slices was a 32-bit 7z SFX workaround; InnoSetup 64-bit has no 4GB limit. Set `DiskSpanning=no` → one `.exe`; verify e2e install. **Ship together with signing** — a signed-but-multi-file installer drops users *past* the SmartScreen wall instead of at it. Update `index.html` copy that still says "4 files". (Confirmed `DiskSpanning=yes`.) | M | `scripts/installer_premium.iss:32-36`, `build_installer_premium.bat:64-73`, `docs/public-launch/index.html:748,773` |
| 5.2 | **signtool pipeline (inert until cert exists).** Add timestamped `signtool sign /fd SHA256 /tr <rfc3161> /td SHA256` after `iscc` and on inner `kali-desktop.exe`+`kali-backend.exe`. Read cert from env/secret so it commits cleanly and no-ops when absent. (Confirmed: zero signtool anywhere.) | M | `scripts/build_installer_premium.bat:51`, `installer_premium.iss:9` |
| 5.3 | **Script the staging step (fail-fast).** `build_installer_premium.bat` only *prints* the xcopy hint — staging fresh `kali-backend`/`kali-desktop.exe` into `premium_stage` is a manual step → stale-bits-in-signed-installer risk. Make it a fail-fast `robocopy /E` (NOT `/MIR` — wipes `.hf_cache`) inside the `.bat` before `materialize_hf_symlinks.py`. | M | `scripts/build_installer_premium.bat:23` |
| 5.4 | **Delete dead `ggml-base.bin` (147MB) + dedupe Silero VAD.** Leftover whisper.cpp model from the abandoned Rust-STT path, referenced nowhere (confirmed present; STT uses faster-whisper). Script the delete in the staging step. | S | `dist_premium/premium_stage/models/ggml-base.bin` |
| 5.5 | **Updater: minimum = delete the dead block.** `tauri-plugin-updater` is absent from `Cargo.toml`/`lib.rs` (inert), pubkey is `base64("test_pubkey_placeholder")`, endpoint is unowned `api.kali-os.com`. Delete the `plugins.updater` block so the shipped config doesn't advertise a fake key/unowned host. **Full path (separate, code-mockable):** add the plugin, run `tauri signer generate`, swap pubkey, target a real host (host = human-gate); per spec §4 Path 2, version the app-shell separately from the 1.35GB model payload so a routine update is MBs not 4.9GB. | S→L | `src-tauri/tauri.conf.json:53-58`, `Cargo.toml`, `lib.rs:216-217` |
| 5.6 | **Reconcile installer pipelines.** `tauri bundle.targets=["msi"]` produces an MSI the team doesn't ship. Set `bundle.targets` to what's actually shipped (or document why MSI is generated); confirm `installer_lite.nsi` is an intended SKU or retire it. | S | `src-tauri/tauri.conf.json:35`, `scripts/installer_lite.nsi` |
| 5.7 | **Deferred-install landing OS-detection + `kali://` redirector** (static site, against mock hosts). Drafted `index.html` exists but hardcodes separate Windows/Android buttons with no OS-detect and no macOS/iOS store links. Reconcile producer (`kali://`) vs consumer vs the dead `https://kali.app` linkBase so one format is canonical. Build now; go-live needs the owned domain + assetlinks/AASA host. | S | `docs/public-launch/index.html`, `mobile/lib/core/share_config.dart:14` |
| 5.8 | **App-store CI scaffolding.** No `.github/` exists. Author GitHub Actions for desktop build + signtool, fastlane lanes for Play (`supply`) + App Store (`deliver`/TestFlight), dry-run with secrets stubbed. Go-live waits on accounts (human-gates). | M | NEW `.github/workflows/*`, `mobile/ios/fastlane/*` |

---

## 3. 🚧 HARD GATES — only Vasily can clear

| Gate | Unblocks | Cost / effort | Proceed against mock until cleared? |
|------|----------|---------------|--------------------------------------|
| **EV code-signing certificate** (cloud-HSM CA, legal-entity vetting) | Removes SmartScreen "Unknown publisher" wall on the Windows installer — the single largest install-funnel drop | ~$300-600/yr; **1-3 week org-verification lead time = THE long pole**. Start NOW. | ✅ signtool pipeline (WS-5.2) commits inert, no-ops without cert |
| **Registered + owned domain** (kali.app is parked/unowned; api.kali-os.com unowned) | **Keystone gate** — unblocks updater feed + CDN canonical paths + landing-live + Android App Links (assetlinks.json) + iOS Universal Links (AASA) + deferred-install relay | Domain reg (~$10-50/yr) + DNS. **Buy ONE domain to unblock all of these.** | ✅ all app-side wiring + mock landing (WS-3.x, WS-5.7) code-now |
| **Cloud host / CDN** (Cloudflare R2 + Pages recommended — zero egress, resumable/range) | Self-serve public download of the ~4.9GB installer + APK + `latest.json` + assetlinks.json. A 4.9GB single file WILL get interrupted on consumer connections. | Cloudflare account (free tier viable); + the domain | ✅ upload-on-build script + `latest.json` gen mockable |
| **Provisioned Supabase project** (Postgres + Storage + anon/magic-link auth + RLS) | Marketplace Phase B/C go-live (apply migrations, real catalog) | Free→tier per §10 | ✅ **entire WS-3 builds against `MagicMock` Supabase** + local `supabase start` for RLS |
| **Mac (physical or cloud) + Apple Developer Program** | The **ENTIRE Apple column** — iOS + macOS App Store, TestFlight, notarization. Nothing Apple builds/signs/ships without both. | $99/yr + Mac hardware/rental | ✅ all iOS/macOS config edits (WS-4.1-4.3) land now so it compiles the moment the Mac arrives |
| **Android upload keystore (.jks)** + Play App Signing enrollment | Play-acceptable release (current AAB is debug-signed → rejected) | one-shot `keytool`; secret custody is Vasily's | ✅ `signingConfigs.release` wiring (WS-4.5) against throwaway keystore |
| **Google Play Console account** + Data Safety + content rating | Play listing | $25 one-time + identity verification lead time | ✅ store-listing/privacy/permissions drafts exist in `docs/public-launch/play-store/` |
| **Cloud host for the thin mobile relay** (deferred-link landing + Supabase catalog + optional Pro-voice GPU) | Closes the mobile UGC loop for a **desktop-less friend** (Option C). Without it, mobile dies at the connection screen. | per the host above + GPU pool if Pro-voice | ✅ relay code-mockable against local/mock host; **on-device-lite engine (WS-4.7) needs NO host** |
| **Rotate the live OpenAI key (`…<redacted>`)** | Closes the disclosed-fragment exposure | minutes (Vasily re-issues into `%APPDATA%\KALI\.env`) | ✅ doc-scrub (WS-2.10) is code-now |
| **Telegram bot token** (or reuse `agents/telegram`) | Makes the notifier "телеграм" channel actually deliver | free | ✅ code + mock-delivery test land now (WS-2.9) |
| **Legal-reviewed Privacy Policy / EULA** (drafts exist, counsel-unreviewed, `<PLACEHOLDER>` fields) | Any store listing + any cloud-touching path | legal review | ✅ drafts authored; hosting needs the domain |
| **GPLv3 FFmpeg resolution** — rebuilt LGPL binary (no `--enable-gpl`/x264/x265) OR drop torchcodec's FFmpeg dep OR legal decision | Legally-shippable proprietary installer (current 7 DLLs ship with NO license file) | binary sourcing + legal review | ⚠️ can ship license text alongside now, but doesn't resolve copyleft for a GPL build |
| **M2.1 permission-model product decision** — which destructive verbs need per-action approval vs blanket consent | Public-launch trust (voice now executes real actions) | product/trust call | ✅ deny-by-default enforcement code (WS-2.1) lands now; Vasily tunes the policy |
| **Ollama daemon** (optional) | Local-provider tool round-trip against a real model | — | ✅ httpx mock covers it (WS-1.5c) — only needed if Vasily wants real-model verification |

---

## 4. Dependency-ordered execution sequence

**Phase 0 — Lock the foundation (WS-1).** Nothing else is trustworthy until the loop is proven.
`1.1 (green baseline)` → `1.2 (keystone build→callable)` → `1.3 + 1.4 (schedule + share legs, parallel)` → `1.5 (voice/onboarding/local)` → `1.6 (CI gate)`.
**Unblocks:** every downstream dimension (mobile, marketplace, distribution) can now build on a *trusted* loop rather than faith.

**Phase 1 — Trust & security hardening (WS-2).** Do immediately after Phase 0 because **blocker #1 closing made M2.1 live-dangerous**.
`2.1 (M2.1 — launch blocker)` + `2.2 (Rust token — top security item)` first; then fast wins `2.3, 2.4, 2.10` (<1 day); then `2.5-2.9` as capacity allows. `2.8` (proxy bypass) before any UGC-agent launch.
**Unblocks:** a safe desktop ship + any LAN/relay channel (2.2 is a shared prereq).

**Phase 2 — Marketplace B/C against mocks (WS-3).** Two threads run in **parallel with zero external dependency**:
- Thread A: `3.1 (SQL migrations + RLS)`
- Thread B: `3.2 (CatalogClient rewrite)`
Then `3.5 (browse reconcile)` + `3.6 (zip wiring)` + `3.9 (share-card PNG)` → `3.3 (identity)` → `3.4 (social)` → `3.7 (moderation)` → `3.8 (legacy cleanup)`.
**Go-live gated on:** Supabase project + domain + moderation policy.

**Phase 3 — Platform config + distribution scaffolding (WS-4 + WS-5), parallel with Phase 2.**
- WS-4 config edits (`4.1-4.6`) are cheap and unblock the moment human-gates clear — **land them now**. `4.7 (on-device-lite engine)` is the real mobile 1.0 cost (XL) — start it once Phase 0/1 free up capacity; it's what makes Android/iOS/macOS functional standalone.
- WS-5: `5.1 (single-file)` + `5.2 (signtool)` **ship together**; `5.3, 5.4, 5.5(delete), 5.6` are quick cleanups; `5.7 (landing)` + `5.8 (CI)` build against mocks.
**Go-live gated on:** EV cert + domain + CDN (Windows); keystore + Play account (Android); Mac + Apple Dev (iOS/macOS).

**Critical-path note for the FIRST public platform (Windows beta):**
EV cert (procurement, 1-3wk — **start day 1**) → signtool step (5.2) → single-file collapse (5.1) → CDN host (gate) → hosted privacy/EULA (gate) → landing live (5.7). The three code items run in parallel with cert procurement.

**Risk flag — Rust path:** the 5 blockers are closed in the `engine='python'` path only (`models.py:171`; `kali.yaml` doesn't override). If/when Gate A flips `voice.engine='rust'`, the Python pipeline goes inert and the Rust path proxies to `/chat` — it *would* inherit the correct `_chat_logic` dispatch, but the Rust path is **unaudited and uncovered by these tests**. A parallel Rust-path verification pass is required before that cutover.

---

## 5. Verification strategy

**Built alongside (no manual halfway testing) — the WS-1 suite is the contract:**
- VERIFY-1..4 run with **REAL `SkillExecutor` + `PluginRegistry`** but **stub STT + LLM + TTS** → no torch/F5/whisper deps, runs in seconds, wired into `make test` + pre-push (VERIFY-6). This single suite would have caught blockers #3, #5-register, and the palette gap.
- WS-2 adds permission-enforcer tests (deny-by-default for destructive verbs), a Rust-token middleware test, and the honest-status sweep.
- WS-3 adds `CatalogClient` unit tests against the mock Supabase chain + RLS-policy tests against local `supabase start`.
- WS-4.1-4.5 add `FirstAgentStep.test.tsx` (deploy assertion) and Flutter widget tests for the share-card PNG.
- Heavy on-device F5/STT checks gated **separately** (manual/nightly), never in the per-commit suite.

**ONE consolidated manual + two-device live-verify pass before public rollout** (the hard gate the automated suite *cannot* replace):
1. **Frozen-bundle smoke (RTX machine, Vasily-only):** install the rebuilt 4.2GB Premium installer → confirm the PyInstaller bundle boots, loads F5/whisper, and runs **one real voice "create→works→share" cycle** end-to-end. The e2e tests prove code wiring; they cannot prove the frozen bundle boots on target hardware.
2. **Two-device UGC loop:** Device A (desktop) creates an agent by voice → shares a reel/link → Device B (a second machine / `kali_test_34` emulator per memory — NOT the corrupting `Pixel_7` AVD) installs via `kali://import` → confirms the imported skill is callable. Validates the P2P loop the product is bet on.
3. **Live screenshot of the REACHABLE surface** (per the quality+live-verify rule): trigger real data and screenshot the actual `ActivityWidget`/community tab — do not trust headless tests on nav-unreachable components.

---

## 6. Recommended first workstream to execute

**Start WS-1 (Core-loop e2e test harness) — beginning with task 1.1 then the 1.2 keystone.**

Why:
1. **It is the single highest-leverage work in the entire assessment.** It converts the spine sprint from "claimed fixed" to "proven fixed" and is the prerequisite that lets every downstream dimension build on a trusted loop. Doing feature work first means stacking on faith.
2. **It directly serves Vasily's stated goal** — confidence *without* manual halfway testing (the binding quality+live-verify principle in memory). The whole sprint's value currently rests on faith; this suite is the safety net.
3. **It is pure `code-now`** — zero external gates, runnable immediately, finishes in well under the procurement lead time of the EV cert (which Vasily should kick off **in parallel, today**, since its 1-3 week verification is the real critical path to a public Windows download).
4. **1.1 is a 30-minute green-baseline fix** (stale `anthropic` patch target) that unblocks trusting the rest of the suite — a clean, fast first win before the 1.2 keystone.

Concretely: fix the 6 red `agent_generator` tests (1.1), then build `tests/e2e/test_core_loop_build_deploy.py` with a real `SkillExecutor` (1.2). The moment 1.2 is green, the loop is proven and Phase 1 security hardening (M2.1 + Rust token) can proceed on solid ground.