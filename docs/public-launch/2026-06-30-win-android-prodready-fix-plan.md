# KALI — Windows + Android Prod-Readiness Fix Plan

**Date:** 2026-06-30
**Source:** adversarially-verified 21-agent audit (`workflow wf_10d426d7-eba`): 35 confirmed findings (4 P0, 19 P1, 12 P2), false-positives filtered. Scope = Windows desktop + Android only (iOS/macOS out). Directive (Vasily): fix ALL code-fixable P0/P1/P2, pause before merge.
**Branch:** `feature/win-android-prodready`. Gates: `pytest -m core_loop`, whole-tree `flutter test` (NOT `test/standalone` — omits scheduling/), `cargo test`, `pnpm -C ui test`.

## Vasily-gated / hardware-live-verify (NOT code — for the launch lane)
- **android-keystore (P0):** generate upload keystore (keytool) + Play Console app + service-account; no shippable Android artifact until done. Aligns with the Armenia-entity long pole.
- **GPL-DLL prune verification (P1):** the prune code is fixable here; confirming the SHIPPED bundle is clean must be checked on the RTX/build machine.
- **safety-gate policy (P1/P2):** strongest fix is a POLICY decision (curated source vs skills-only community vs sandboxed agent.py) — Vasily ratifies before full implementation. Interim code hardening landed regardless.

## Live-test checklist (Vasily, after code lands) — RTX desktop + real Android phone
1. RTX: frozen-bundle reel via libopenh264, **no libx264/libx265 in `_internal/av.libs`** + F5 Russian speaks E2E.
2. RTX: voice create→works→share on the FROZEN build; deploy-confirm («даже не думай» ≠ deploy, «да запускай» = deploy).
3. RTX: skip-key first-run → Russian «Настройки → Модель» CTA (not English "I'm sorry…").
4. RTX: rename `kali-backend.exe` → UI shows honest "backend failed" + log path within ~6s (not infinite reconnect).
5. Phone: reminder fires across **app-killed + idle/Doze**; toggle-off stops; snooze +1h shifts. (the c89e18c native-init class — fake-gateway-blind.)
6. Phone: two-device `kali://pair` QR → MainScreen + token persisted; manual-IP fallback works.
7. Phone: `kali://pair?ip=evil.com` REJECTED; `…?ip=192.168.x.x` succeeds (token never to public host).
8. Phone: `kali://import` → consent sheet (name+desc) BEFORE install → appears in «Мои агенты»; malformed → honest `importFailed`, no crash.
9. Phone: `allowBackup=false` → bmgr backup/restore, no secure-storage crash, agents not in Google backup.
10. Cross: Cyrillic reminder round-trips on a non-UTF-8 Windows codepage (no UnicodeEncodeError/mojibake).

---

## Fix clusters (suggested order)

### Android
**C1 — Deep-link reachability + security** (`AndroidManifest.xml`, `deep_link_service.dart`)
- `and-pair-deeplink-no-intent-filter` **P0** — `kali://pair` has NO intent-filter → tethered pairing dead. Add VIEW intent-filter host="pair" (scheme kali, BROWSABLE+DEFAULT). Check: `adb am start -d 'kali://pair?ip=…&token=…'` launches to MainScreen.
- `and-sec-pair-arbitrary-host` **P1** — pair accepts arbitrary public host → token exfil. Reject non-loopback/RFC1918/CGNAT + DNS names in `parsePairLink`. Check: `evil.com`/`1.2.3.4`→null, `192.168.1.5`→PairInfo.
- `and-sec-import-no-consent` **P2** — import silently installs+flips+requests perm. Decode (pure) first → confirm sheet (name+desc) → persist only on confirm. Check: import shows dialog, no save/perm until Confirm.
- `android-allowbackup-default-leaks-agents-keys` **P1** — no `allowBackup=false`/extraction rules. Set `allowBackup="false"`. Check: aapt dump shows allowBackup=false.
- `and-test-deeplink-import-to-myagents-unproven` **P2** — add e2e widget test import→«Мои агенты».

**C2 — Reminder scheduler concurrency + perf** (`reminder_scheduler.dart`, `my_agents_screen.dart`, `main_screen.dart`, `notification_gateway.dart`)
- `and-syncall-concurrency-race` **P0** — no concurrency guard → overlapping syncAll wipe fresh schedules. Serialize via `Future<void>? _inFlight` (coalesce ≤1 running +1 queued). Check: `Future.wait([syncAll×3])` → stable pendingCount.
- `and-bootstrap-redundant-syncall-perf` **P2** — per-tile syncAll+perm = O(N²). Hoist to screen-level once.
- `and-honest-unawaited-syncall-resume` **P2** — fire-and-forget syncAll → unhandled async. Await in guarded helper + catch/log.
- `and-honest-permission-default-true` **P2** — `requestPermission()` null→true on Android (false success). Default Android null→false (or areNotificationsEnabled).

**C3 — AgentStore crash-safety + import overwrite** (`agent_store.dart`, `bundle_importer.dart`, `my_agents_screen.dart`)
- `and-agentstore-list-whole-store-failure` **P1** — one corrupt JSON → list() throws → ALL reminders+«Мои агенты» break. Per-entity try/catch skip; atomic save (.tmp+rename). Check: 2 valid +1 `{` +1 missing-name → list returns 2, no throw.
- `and-import-overwrites-existing-agent-silently` **P1** — re-import loses enabled/snooze. Carry forward enabled+snoozeUntil, or "updated" snackbar.
- `and-honest-myagents-no-error-branch` **P2** — FutureBuilder ignores hasError → empty-state on failure. Add error/retry branch.

**C4 — Cold-start + chat crash-safety** (`main.dart`, `standalone_chat_screen.dart`)
- `and-crash-main-unguarded-init` **P1** — main() init throw → white-screen. Per-side-effect try/catch, runApp unconditional.
- `and-crash-standalone-chat-setstate-after-dispose` **P1** — setState after await no mounted guard. Gate every post-await setState with `if(!mounted)return;`.
- `and-ux-standalone-chat-unbounded-history` **P2** — resends ENTIRE history each turn. Cap last N=20 + clear-chat action.

**C5 — Secrets + network hardening + logging** (`websocket_client.dart`, `token_store.dart`, `llm_settings_store.dart`, `network_security_config.xml`)
- `and-sec-ws-token-logged` **P1** — token in WS URL logged. Log host/port only; redact token.
- `and-sec-secure-storage-default-android` **P2** — default options, EncryptedSharedPreferences not explicit. Pass `AndroidOptions(encryptedSharedPreferences:true)`.
- `android-cleartext-base-config-wide-open` **P2** — cleartext for ALL hosts. Code-level guard rejecting non-RFC1918 cleartext + test.

**C6 — Reminder-config parsing edges + key-save UX** (`reminder_config.dart`, `ru_interval_parse.dart`, `llm_settings_screen.dart`)
- `and-cron-hourfield-misparse` **P2** — `0 */2 * * *` misparsed as minutes→15m spam. Field-position-aware parse. Check: `*/30…`→0.5h, `0 */2…`→2.0h.
- `and-nextfire-...window-end24` **P2** — «вечера» PM-shifts only end. Shift start too when PM marker + start<12.
- `and-ux-llmsettings-empty-key-silent-save` **P2** — blank key "saved" → dead-end. Reject empty, distinct error.

**C7 — Build/release config** (`pubspec.yaml`, `build.gradle.kts`)
- `android-versioncode-pinned-to-one` **P2** — no `+N` → Play rejects 2nd upload. `version: 0.1.0+1`.
- `android-release-falls-back-to-debug-signing` **P2** — release silently debug-signs when keystore absent. Fail-fast release AAB under CI/RELEASE gate.

### Windows
**C8 — Builder flow: collision/data-loss + validation** (`flow.py`, `skill_generator.py`, `deployer.py`, `intent_classifier.py`)
- `win-builder-skill-name-collision-overwrite-dataloss` **P0** — colliding slug overwrites + deploy-fail rmtree DELETES existing agent. Collision detect / de-dup name; skip rmtree when dir pre-existed.
- `win-intent-llm-template-not-validated` **P1** — unvalidated template + crash on non-numeric confidence. Validate template set; try/except float(confidence)→regex fallback.
- `win-interval-zero-minutes-silent-no-schedule` **P2** — `*/0` cron → never scheduled. Clamp minutes ≥1.

**C9 — Async task-lifetime (GC-cancel)** (`voice/pipeline.py`, `main.py`)
- `win-crash-voice-mainloop-gc-cancel` **P1** — fire-and-forget main loop GC-cancelled. Store task ref + done-callback.
- `win-crash-model-download-gc-cancel` **P1** — download task GC-cancel → UI hangs. Store ref + failure event.
- `win-chat-speak-task-gc` **P2** — auto-speak task GC. Retain in app.state set.

**C10 — Voice correctness + honest-fail** (`voice/stt.py`, `voice/pipeline.py`, `voice/remote_pipeline.py`)
- `win-stt-hallucination-filter-drops-valid-utterances` **P1** — filter blanks utterances with «редактор/корректор». Anchor to full-utterance/phrase, not substring.
- `win-voice-deploy-confirm-substring-false-positive` **P1** — «да» substring → «даже не думай» deploys. Word-boundary match; ambiguous→re-ask.
- `win-honest-remote-voice-debug-print-swallow` **P1** — `print('DEBUG:')` + swallowed STT exc → phone mute. logger + publish voice.error event.
- `win-chat-multi-toolcall-dropped` **P2** — multi-intent drops all tool calls but first. Iterate ≤N, concat; or honest note.

**C11 — Untrusted-bundle ingestion security** (`skills/installer.py`, `catalog/package.py`, `catalog/installer.py`, `builder/safety_gate.py`, `catalog/content_gate.py`)
- `win-sec-catalog-tar-traversal` **P1** — catalog extract no traversal containment. `extractall(filter='data')` or resolve+is_relative_to.
- `win-package-unpack-extra-file-checksum-gap` **P1** — unpack extracts UNLISTED files. Assert extracted set == checksums.json keys.
- `win-sec-safety-gate-bypassable-scripts-exec` **P1** — bundle scripts run gated only by bypassable AST. Reject `scripts/` in shared bundles (declarative-only); downgrade docstring honesty. (policy: Vasily)
- `win-safety-gate-non-adversarial-on-untrusted-bundles` **P2** — default-deny agent.py from non-curated. (policy)
- `win-sec-bundle-decompression-bomb` **P2** — no size cap. Sum member sizes, reject > 25MB.
- `win-content-gate-russian-injection-blind` **P2** — prose gate English-only. Add RU injection needles.
- `win-sec-publish-skip-safety-exposed` **P2** — `/skills/publish` body can disable safety gate. Hardcode False on HTTP surface.

**C12 — Sandbox egress hardening** (`sandbox/http_client.py`, `agents/web-surfer/scripts/surf.py`, `agents/notion/agent.py`)
- `win-sec-ssrf-dns-rebinding-toctou` **P2** — DNS resolved separately from connect. Pin connection to vetted IP.
- `win-sec-websurfer-self-whitelist` **P2** — whitelists caller host → defense inert. Require SKILL.md-declared domains.
- `win-sec-sandboxclient-bypasses-ratelimit-audit` **P2** — agents construct client directly, bypass rate/audit. Route via `for_agent`.

**C13 — Persistence + encoding + boundary** (`skill_templates/base.py`, `routines.py`, `main.py`, `llm_router.py`)
- `win-crash-skill-data-no-utf8-encoding` **P1** — JSON r/w no encoding=utf-8 → Cyrillic corruption on Windows codepage. Add `encoding='utf-8'` both calls.
- `win-routines-relative-path-and-corrupt-json` **P2** — CWD-relative path + crash on corrupt. appdata_dir() + try/except→{}.
- `win-sec-saveenv-naive-parser` **P2** — newline in value injects env line. Strip/reject control chars; proper dotenv writer.
- `win-honest-briefing-bare-except-pass-no-log` **P2** — 5 bare except/pass. Add logger.debug exc_info.
- `win-crash-llmrouter-inner-fallback-uncaught` **P2** — double-outage re-raises uncaught. Wrap → honest error response.

**C14 — Chat UX honest-fail + test coverage** (`main.py`, `ui/.../ChatInput.tsx`, `tests/`)
- `win-ux-chat-nokey-english-error` **P1** — skip-key → English dead-end. Detect no-key → Russian «Настройки→Модель» + source='no-key' + inline CTA.
- `win-test-chat-endpoint-uncovered` **P2** — `/chat` no direct test. Add core_loop POST /chat tests.
- `win-test-chatinput-component-untested` **P2** — ChatInput zero tests. Add vitest cases.

**C15 — Backend-start honest-fail** (`src-tauri/src/lib.rs`, `backend/mod.rs`, `ui/src/App.tsx`)
- `win-crash-backend-start-failure-not-surfaced` **P2** — spawn fail stderr-only → infinite reconnect. Emit `backend://failed` event + UI honest message.
- `win-sec-ws-token-in-url-logged` **P2** — token in /ws query captured by TraceLayer span. Custom MakeSpan path-only.

**C16 — Installer packaging integrity** (`build_backend_premium.py`, `build_installer_premium.bat`, `installer_premium.iss`)
- `win-pkg-gpl-x264-x265-in-avlibs` **P1** — GPL libx264/x265 DLLs ship (copyleft blocker). Post-build prune (keep libopenh264 BSD). Verify on RTX.
- `win-pkg-webview2-ps1-not-staged-by-build` **P2** — install-webview2.ps1 never staged. Add to .iss [Files].

## Execution
Subagent-driven TDD per cluster (fresh implementer + review). P0 clusters (C1,C2,C8) first, then P1-heavy, then P2. Whole-tree gates green per cluster. Pause before merge with summary + the live-test checklist above.
