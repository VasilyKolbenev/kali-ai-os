# KALI — Pre-release Audit (2026-06-08)

Run before the desktop clean-install test and the mobile real-device test.
Method: mechanical sweep (ruff / tsc / clippy / flutter analyze / pytest / grep) +
6 parallel zone finders (kernel, security, ui, rust, mobile, build) + adversarial
verification of the top Critical/High findings (a second agent tried to refute each).
50 raw findings; 8 independently verified; 2 finder claims refuted on verification.

## Verdict

The shipped Premium payload has **no leaked secrets** and the Rust voice core is clean.
But there are **two confirmed Critical security holes** (both in the share-an-agent /
LAN paths, must fix before any friend gets a build) and a cluster of **functional bugs
on the exact clean-install and mobile flows about to be tested** — the worst being that
onboarding never saves the LLM key, so a fresh install ends with a non-working chat.

None of these block *running* the installer; several will make the demo misbehave.

## Mechanical results

| Check | Result |
|---|---|
| `ruff` (kernel/scripts/agents) | 182 issues, all style (E501/W293/I001/F401) — no logic |
| `tsc --noEmit` (ui) | clean (exit 0) |
| `cargo clippy` (src-tauri) | clean — 0 warnings |
| `flutter analyze` (mobile) | 1 error (broken template `widget_test.dart`), 2 warnings, 11 info |
| `pytest` (full) | native access-violation in pytest-asyncio teardown (~45%) — see DEV-1 |
| secret regex / `eval`/`exec` / `yaml.load` / bare `except:` | clean |

## Confirmed Critical / High (verified by a second agent)

| ID | Sev | File:line | Issue | Fix gist |
|---|---|---|---|---|
| SEC-1 | **Critical** | `kernel/catalog/installer.py:37` | `.kali-agent` install joins the **attacker-controlled manifest `name`** onto the agents dir with no validation → path escape → arbitrary file write / drop into Startup → code exec on next login. Reachable via `POST /catalog/install` — the core "friend installs a shared agent" flow. Zip-slip check uses the already-escaped base. | Validate `name` as a single safe component (allowlist `[a-z0-9-]`, reject `/ \ ..` / drive / anchor), assert containment via `os.path.commonpath` before `unpack`. The builder generators already do this; the installer omits it. |
| SEC-2 | **Critical** | `src-tauri/src/backend/mod.rs:50` | `CorsLayer::permissive()` on a backend bound to **`0.0.0.0:3006` with no auth**. Any website the user visits can read `/chat` and `/dashboard` cross-origin; any LAN host can `POST /chat` (burn cloud credits) or `PATCH /config` (rewrite provider/routing). | Replace permissive with a fixed origin allowlist (mirror the Python one); gate mutating proxy routes behind a shared token; default-bind `127.0.0.1`, make `0.0.0.0` opt-in. |
| UI-1 | High (was Critical) | `ui/src/components/Onboarding/steps/ApiKeyStep.tsx:31` | Onboarding sends `api_key_<provider>` but the backend only accepts `<provider>_key`, so **the LLM key is silently never saved**. `/llm/test` validated it, UI shows "✓ работает", advances — then chat/builder have no key. Hits the clean-install path directly. | Send `{ provider, [`${selected}_key`]: key }`; assert response `keys` non-empty before advancing. |
| KER-1 | High | `kernel/main.py:1186` | `/chat` auto-speak `finally` **restarts the mic recorder unconditionally** (stop side is guarded, restart isn't). With voice OFF, sending a chat message opens the mic with no UI "listening" state; nothing consumes the queue → mic stays hot. | Capture `was_recording` before stop; only restart if it was recording (mirror `_play_tts_with_guard`). |
| UI-2 | High | `ui/src/components/Chat/ChatInput.tsx:51` | Voice toggle reads `status.available` (always true if pipeline exists) instead of `started`, so the J button always shows green, every click calls `voiceStop()`, and **start is unreachable** from the main screen. | Use `Boolean(status.started)` at :51 and :212. |
| UI-3 | High | `ui/src/components/Chat/ChatInput.tsx:149` | Main mic button uses the Web Speech API, **unsupported in WebView2** → dead button with an English "Use Chrome" error; Space hotkey drops the error into chat. | Route mic through the backend STT path (`/voice/transcribe`, like Voice Builder) or hide the button in the Tauri build. |

## Finder-reported High (capped out of verification — plausible, not independently re-checked)

| ID | Sev | File:line | Issue |
|---|---|---|---|
| UI-4 | High | `ui/src/components/Onboarding/steps/MicTestStep.tsx:87` | Hey-Jarvis step has no skip in the `listening` state; if `voiceStart` fails it still enters `listening` → onboarding dead-end. (Wake model is EN-trained; RU «Джарвис» scores ~0.02.) |
| UI-5 | High | `ui/src/hooks/useOnboardingGate.ts:28` | Backend still booting at launch → fetch fails → user treated as not-onboarded → returning users get the wizard again, no retry. |
| UI-6 | High | `ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx:140` | Navigating away while `getUserMedia` is pending leaves the mic on (ghost recording, ghost submit). |
| MOB-1 | High | `mobile/lib/core/websocket_client.dart:14` | `isConnected = _channel != null` → connect "succeeds" for an unreachable server; lands on a dead MainScreen. Directly hits the real-phone test. |
| MOB-2 | High | `mobile/lib/presentation/settings_screen.dart:286` | Disconnect never closes the socket; reconnecting to a corrected IP is silently dropped (`if _channel != null return`). |
| MOB-3 | High | `mobile/lib/presentation/voice_screen.dart:52` | Mic keeps recording/streaming after leaving the Voice tab (dispose only kills the animation). |
| BLD-1 | High | `kernel/llm_router.py:119` | `auto_route=false` (explicit local-only privacy) **falls back to cloud** on any local-LLM failure → user content shipped to OpenAI/Anthropic silently. |
| BLD-2 | High | `agents/web-surfer/SKILL.md` + `agents/automation-scheduler` | Both ship and are advertised to the LLM as tools but have no executor → guaranteed "Skill not found" error on e.g. «найди в интернете». |

## Medium

| ID | File:line | Issue |
|---|---|---|
| KER-2 | `kernel/voice/stt.py:50` | Whisper HF cache resolves under the install dir; `makedirs` outside `try` → STT crashes on an all-users (Program Files) install. |
| KER-3 | `kernel/main.py:546` | First-run Whisper download (~480 MB) runs inside lifespan startup → `/health` blocked → app looks hung on first launch. |
| KER-4 | `kernel/main.py:626` | Background tasks via `create_task` with no stored ref (GC can cancel mid-download); recurs at :421, :1197, pipeline.py:162, long_term_memory.py:40. |
| KER-5 | `kernel/agent_runtime/protocols/inprocess.py:82` | Sync `handle_action` called inline in async → blocking network I/O (weather agent) freezes the event loop up to 10s. |
| SEC-3 | `kernel/sandbox/http_client.py:180` (+ `network_proxy.py:122`) | Domain allowlist not re-checked on HTTP redirects → SSRF bypass (169.254.169.254, localhost). |
| UI-7 | `ui/src/components/Onboarding/steps/ModelsDownloadStep.tsx:34` | Download step advances only via one-shot WS event, no polling fallback → stuck-forever risk; «Повторить» = full page reload. |
| UI-8 | `ui/src/components/AgentStore/AgentStore.tsx:65` | Store bootstrap failure swallowed → renders as a convincing empty store, no retry (same in AgentPanel). |
| UI-9 | `ui/src/components/VoiceVisualizer/VoiceVisualizer.tsx:47` | getUserMedia race overwrites `audioRef` → leaks live mic streams (OS indicator stays lit). |
| UI-10 | `ui/src/components/VoiceBuilder/useRmsVad.ts:39` | VAD fires after 1.5s initial silence with no speech-seen requirement → auto-submits empty audio to the builder. |
| UI-11 | `ui/src/components/Dashboard/Dashboard.tsx:75,92` | Weather city `"Moscow"` and currency `"₽"` hardcoded, no setting. |
| RUS-1 | `src-tauri/src/backend/proxy.rs:15,43,75` | Proxy `reqwest::Client` has no timeout → a slow/booting Python hangs mobile-facing `/dashboard`,`/agents`,`/chat` forever. |
| RUS-2 | `src-tauri/src/backend/mod.rs:54` | Port-bind failure on :3006 is silent (`eprintln` only) → whole backend dead, app looks fine. |
| MOB-4 | `mobile/lib/presentation/connection_screen.dart:18` | IP field pre-filled `10.0.2.2` (emulator-only) → real-phone dead-end; no discovery/QR. |
| MOB-5 | `mobile/lib/presentation/voice_screen.dart:60` | Mic-permission denied leaves the orb stuck in LISTENING, no feedback/Settings path. |
| MOB-6 | `mobile/lib/presentation/settings_screen.dart:19` (+ agent_store) | Raw `Dio()` no timeouts → infinite spinner when server unreachable; ad-hoc clients ignore the configured `dioProvider`. |
| MOB-7 | `mobile/lib/presentation/main_screen.dart:39` | Tab switch destroys screen State → chat history wiped, every tab refetches. Use `IndexedStack`. |
| MOB-8 | `mobile/lib/core/websocket_client.dart:49` | Reconnect backoff never grows (reset runs every attempt) → 1s reconnect spam forever, no cap. |
| MOB-9 | `mobile/test/widget_test.dart:16` | References non-existent `MyApp` → `flutter test` fails to compile. |
| BLD-3 | `kernel/voice/wake_word.py:125` | Detector fires on ANY of the 9 bundled models (alexa/mycroft/timer…); configured `wake_word` is never used to filter → false wakes + unintended capture. |
| BLD-4 | `scripts/installer_premium.iss:7` | Version skew: installer/backend `0.2.0-beta` vs desktop shell/ui `0.1.0` vs stale nsi `0.1.0-premium`. |

## Low / hygiene

| ID | File | Issue |
|---|---|---|
| SEC-4 | `kernel/main.py:565` | `[*]` CORS + `allow_credentials=True` default — inert in the shipped app (Tauri injects an allowlist; see refuted REF-2) but a footgun for dev/manual runs. |
| SEC-5 | `kernel/catalog/package.py:103` | Zip-slip guard uses `startswith` (sibling-dir bypass) + tainted base; currently masked by `zipfile.extract` sanitization. |
| KER-6 | `kernel/voice/remote_pipeline.py` (~10×), `skills/publisher.py` | `print()` on the production WebSocket voice path — bypasses the file logger. |
| RUS-3 | `src-tauri/src/backend/ws.rs:103` | WS sibling task not aborted on half-closed connection → lingering task (self-heals on next event). |
| RUS-4 | `src-tauri/src/backend/http.rs:74` | Synchronous fs reads in async handlers (config/skill/cache) — fine today, blocks if files grow. |
| UI-12 | `ui/src/components/AgentStore/AgentStore.tsx:203` etc. | RU/EN mixed user-visible strings across shipped screens; `language` setting not respected. |
| MOB-10 | `mobile/lib/presentation/dashboard_screen.dart:268` | Dashboard shows fabricated data (+18°C, ₽4,200, fake insight) on fetch failure → reads as live. |
| MOB-11 | `mobile/lib/presentation/share_to_reels_screen.dart:175` | "Publish to Reels/TikTok" CTA fakes an export (snackbar only) + fake engagement counts. |
| MOB-12 | `mobile/android/app/build.gradle.kts:19` | Placeholder `com.example.kali_mobile` appId + release signed with debug key. |
| BLD-5 | `src-tauri/tauri.conf.json:57` | Updater ships placeholder pubkey + unowned `api.kali-os.com` endpoint (inert — plugin not enabled). |
| BLD-6 | `agents/web-surfer/scripts/surf.py:34` | `fetch_url` accepts `file://`/intranet (dead code today; lethal once script-exec lands). |
| BLD-7 | `scripts/build_release.bat:13` + `build_desktop.py` + `installer_premium.nsi` | Three stale/duplicate build pipelines (require removed RVC models) next to the real Premium chain. |
| BLD-8 | `agents/system/manifest.yaml:3` | Hardcodes the founder's GPU ("RTX 5070") in shipped tool descriptions fed to the LLM. |
| BLD-9 | repo root | Scratch debris: `fix.py`, `test_whisper.py`, `backend_*.log`, `refined_dashboard*.png`, `tmp8h7_kxl4/`, audio scratch, empty `services/`+`skills/` dirs. |

## Refuted on verification (finder over-claims — recorded for honesty)

- **REF-1** `kernel/entry.py:39` — claimed `os.kill(pid,0)` *terminates* the running backend on Windows. **False:** sig 0 = `CTRL_C_EVENT`, never `TerminateProcess`; verified empirically the backend survives. Real residual is the opposite polarity (a live cross-console backend is misread as stale) and is already mitigated twice (uvicorn bind on :3005 + Tauri health-check). → Low hygiene: replace the probe with `psutil.pid_exists`.
- **REF-2** `kernel/main.py:565` Python CORS — claimed wildcard-with-credentials is shipped-and-exploitable. **False:** the Tauri shell injects a restricted `KALI_CORS_ORIGINS` allowlist (`lib.rs:18,158`), so the shipped Python port is not wildcard. → downgraded to Low (SEC-4, dev-run footgun).

## Dev-infra

- **DEV-1** Full `pytest` crashes with a native access violation during pytest-asyncio fixture teardown (~45% through, `<no Python frame>`). A native lib (onnx/portaudio/torch) keeps threads alive past a test; the event-loop finalizer touches freed memory. This is the root of the known "isolation flakiness". Not a product bug; blocks a reliable full-suite green. Fix later: isolate ML/audio tests into their own process (`-p no:cacheprovider` + `--forked`/subprocess), or tear those fixtures down explicitly.

## Triage

**A — Fix before the DESKTOP clean-install test (functional, cheap, demo-visible):**
UI-1 (no LLM key — top blocker), UI-2 (voice toggle), UI-3 (dead mic button), UI-4
(onboarding dead-end), UI-5 (gate retry), KER-1 (mic reopen), BLD-3 (wake-word filter),
BLD-2 (broken agents), BLD-8 (RTX 5070), UI-11 (Moscow/₽), KER-3 (health-blocking download).

**B — Security, MUST fix before any friend gets a build (not blocking the solo test):**
SEC-1 (catalog path traversal), SEC-2 (Rust CORS/auth), BLD-1 (privacy cloud-leak),
SEC-3 (SSRF redirects), SEC-5 (zip-slip).

**C — Fix before the MOBILE real-phone test:**
MOB-1 (isConnected), MOB-2 (Disconnect), MOB-3 (mic-after-tab), MOB-4 (10.0.2.2),
MOB-6 (timeouts), MOB-5 (perm denied), MOB-9 (broken test).

**D — Follow-up (after the milestone):** remaining Mediums/Lows, version skew (BLD-4),
hygiene (BLD-9), DEV-1, KER-2/4/5, RUS-1..4, UI-6..10, MOB-7/8/10/11/12, BLD-5/6/7.
