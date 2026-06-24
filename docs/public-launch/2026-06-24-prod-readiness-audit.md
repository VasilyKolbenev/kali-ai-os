# KALI — Prod-readiness audit (code-level)

> 2026-06-24. 6-dimension multi-agent audit (56 agents). **40 findings confirmed** by adversarial verification out of 50 raw (10 killed as false-positive / by-design). Severity = the verifier's re-assessed value for a PUBLIC launch.

## Verdict on «prod-ready, no hardcode, no bugs»

**It does not hold — but it is not a swamp of hidden bugs either.** 4 blocker + 10 high + 10 medium + 16 low. Honest breakdown:

- **Most blockers/highs are KNOWN launch prerequisites, not hidden bugs** — code-signing (EV cert), FFmpeg GPLv3, mobile standalone (LAN-only), placeholder identifiers (`com.example`), JARVIS IP. Already on the human-path roadmap; the audit confirms them at code level.
- **New code-level findings worth attention** (less emphasized before): the backend binds `0.0.0.0` with **no auth** on any endpoint (LAN control-plane exposed); wildcard CORS + `allow_credentials` on that unauthenticated API; the sandbox network whitelist is **dead code** — first-party agents call the network directly, bypassing the proxy (confirms the M2.4 analysis).
- Adversarial verification **killed 10 of 50** raw findings (false-positive / by-design), so the 40 below are real.

**For the desktop-installer rebuild + your test:** none of the 4 blockers prevent a *testable* rebuild — they gate *distribution*, not local testing (signing → SmartScreen wall; FFmpeg → legal; mobile → separate surface; `0.0.0.0` → only matters off-localhost). So we rebuild and you test the real artifact, with these as the known distribution gates.

## Summary

- By severity: **blocker**=4, **high**=10, **medium**=10, **low**=16
- By dimension: build=7, platforms=7, security=6, hardcodes=7, frontend=7, correctness=6

## BLOCKER (4)

### [build] No code-signing step anywhere in the build — every install hits SmartScreen "Unknown publisher"
- `scripts/build_installer_premium.bat:51`
- **Evidence:** Line 51: `"%ISCC%" scripts\installer_premium.iss` is the final step — no signtool follows; grep for signtool/certificateThumbprint/digestAlgorithm across scripts/, tauri.conf.json, Cargo.toml, build-tauri.bat returns empty.
- **Fix:** Neither kali-desktop.exe (Tauri shell), kali-backend.exe, nor the final KALI-Premium-Setup-*.exe is Authenticode-signed. Non-tech target users (строитель/врач/таксист) downloading a ~5 GB unsigned exe from a Drive link hit the full-screen "Windows protected your PC" wall and abandon — the single largest install-funnel drop. Acquire an EV (instant SmartScreen trust) code-signing cert and add a timestamped signing step after the Tauri build and after iscc: `signtool sign /fd SHA256 /tr <rfc3161-url> /td SHA256 <file>` for kali-desktop.exe, kali-backend.exe, and the setup .exe. Must land before any public download link.

### [build] GPLv3 FFmpeg DLLs shipped inside the proprietary installer with no license/NOTICE — copyleft conflict
- `scripts/installer_premium.iss:65`
- **Evidence:** installer_premium.iss:65 copies `premium_stage\*` recursively, which includes `models/ffmpeg/avutil-60.dll` whose embedded string reads `libavutil license: GPL version 3 or later` (also `--enable-gpl`, `libx264` present); no LICENSE/COPYING/NOTICE file sits alongside the 7 DLLs.
- **Fix:** 7 FFmpeg DLLs (avcodec-62, avformat-62, avfilter-11, etc., ~228 MB) are built --enable-gpl --enable-version3 with libx264/libx265 and ship inside a README.md:180 "Proprietary software" product. GPLv3 copyleft conflicts with proprietary/paid distribution. Before any public/commercial launch: swap for an LGPL FFmpeg build (no --enable-gpl, no x264/x265), or drop torchcodec's FFmpeg dependency (build script already notes F5 falls back to soundfile). At minimum, bundling any open-source binaries requires shipping their license text alongside.

### [platforms] Mobile app is LAN-only: hardcoded to a desktop backend at http://<ip>:3006 — a friend with no desktop cannot use it (kills UGC loop)
- `mobile/lib/core/http_client.dart:20`
- **Evidence:** return 'http://$ip:3006$path';  (every screen builds 'http://$ip:3006/...'; connection_screen asks the user to type a 192.168.x.x LAN IP; no cloud/public fallback anywhere)
- **Fix:** The product thesis is 'create agent by voice -> share reel -> friend installs'. But the mobile client can ONLY talk to a desktop KALI on the same Wi-Fi (manual LAN IP entry in connection_screen.dart, ws://$ip:3006 in websocket_client.dart, every REST call in agent_store_screen/chat_screen/settings_screen). A friend who installs from a reel has no desktop and is dead in the water at the connection screen. Before public launch you need a cloud/relay backend (or hosted gateway) the mobile app can reach without a nearby desktop, OR the launch messaging must scope the mobile app as a 'companion to your own desktop' only. This is the single biggest platform-readiness gap.

### [security] Backend binds to 0.0.0.0 with NO authentication on any endpoint — full control plane exposed on the LAN
- `src-tauri/src/backend/mod.rs (+ kernel/main.py):mod.rs:28; main.py:2303, 2226`
- **Evidence:** mod.rs:28 `pub const RUST_BIND_ADDR: &str = "0.0.0.0:3006";` and main.py:2303 `host=os.environ.get("KALI_HOST", "0.0.0.0")`; grep for `Depends(`/`HTTPBearer`/`verify_token` in main.py returns 0 matches.
- **Fix:** Either bind to 127.0.0.1 by default (desktop) OR require a per-install bearer token / device-pairing secret on every mutating route (/settings, /chat, /skills/install*, /config, /llm/test). The mobile app must present that token. Do not ship an all-interfaces bind with zero auth.

## HIGH (10)

### [hardcodes] Tauri updater ships a placeholder public key (base64 "test_pubkey_placeholder")
- `C:/Users/User/Desktop/Jarvis/src-tauri/tauri.conf.json:57`
- **Evidence:** "pubkey": "dGVzdF9wdWJrZXlfcGxhY2Vob2xkZXI="  (base64 decodes to "test_pubkey_placeholder")
- **Fix:** Run `tauri signer generate`, store the private key in CI secrets (not the dummy from build_desktop.py), and replace this pubkey with the real one. Until the updater is actually wired and signed artifacts are produced, remove the entire `plugins.updater` block from tauri.conf.json so no shipped config advertises a fake key. Note: currently INERT — `tauri_plugin_updater` is not present in src-tauri/ (grep clean), so no runtime auto-update occurs yet; severity is high (not blocker) only because of that.

### [hardcodes] Android release build is signed with the debug keystore
- `C:/Users/User/Desktop/Jarvis/mobile/android/app/build.gradle.kts:33`
- **Evidence:** signingConfig = signingConfigs.getByName("debug")  // preceded by "TODO: Add your own signing config ... Signing with the debug keys for now"
- **Fix:** Generate a release upload keystore, add a `signingConfigs.release` reading credentials from a gitignored keystore.properties / env, and point the `release` buildType at it. Google Play rejects debug-signed APKs/AABs; debug keys are also publicly known (no integrity guarantee). Blocker for any Play/store distribution.

### [hardcodes] Placeholder reverse-DNS identifiers: com.example namespace (Android) and bundle id (iOS/macOS)
- `C:/Users/User/Desktop/Jarvis/mobile/android/app/build.gradle.kts:11`
- **Evidence:** namespace = "com.example.kali_mobile"  (iOS/macOS: project.pbxproj:385,564,586 PRODUCT_BUNDLE_IDENTIFIER = com.example.kaliMobile)
- **Fix:** applicationId is already ai.kali.mobile, but the Android `namespace` and the iOS/macOS PRODUCT_BUNDLE_IDENTIFIER are still the default `com.example.*`. Apple rejects com.example bundle ids at submission, and the mismatch complicates App Links/entitlements. Rename namespace to ai.kali.mobile (move MainActivity package) and set all pbxproj bundle ids to your real reverse-DNS under the Apple Developer account before store submission. Also fix android:label="kali_mobile" (AndroidManifest.xml:5) to the real display name.

### [platforms] iOS Info.plist has no NSMicrophoneUsageDescription while the app captures the mic — guaranteed App Store rejection + hard crash on first record
- `mobile/ios/Runner/Info.plist:4`
- **Evidence:** No NSMicrophoneUsageDescription / NSSpeechRecognitionUsageDescription key anywhere in mobile/ios or mobile/macos (grep returned nothing); yet audio_recorder_service.dart calls _audioRecorder.startStream(...) with mic capture.
- **Fix:** iOS terminates the app (SIGABRT) the instant AVAudioSession/record requests the mic without an NSMicrophoneUsageDescription string, and App Review auto-rejects. Add NSMicrophoneUsageDescription (and NSSpeechRecognitionUsageDescription if STT is on-device) to mobile/ios/Runner/Info.plist with a clear Russian/English purpose string, e.g. 'KALI uses your microphone so you can talk to your agents.' Voice is the app's core feature, so this is a launch blocker.

### [platforms] iOS bundle identifier is still the com.example placeholder (com.example.kaliMobile) — cannot be uploaded to App Store / TestFlight
- `mobile/ios/Runner.xcodeproj/project.pbxproj:385`
- **Evidence:** PRODUCT_BUNDLE_IDENTIFIER = com.example.kaliMobile;  (repeated at lines 385/401/418/433/564/586; macOS AppInfo.xcconfig also: PRODUCT_BUNDLE_IDENTIFIER = com.example.kaliMobile and 'Copyright (c) 2026 com.example.')
- **Fix:** Apple rejects com.example.* and the identifier must match a registered App ID. Android was already fixed to ai.kali.mobile (build.gradle.kts line 22) but iOS and macOS were left behind. Set PRODUCT_BUNDLE_IDENTIFIER to ai.kali.mobile (and ai.kali.mobile.RunnerTests) across all configs in mobile/ios/.../project.pbxproj and fix mobile/macos/Runner/Configs/AppInfo.xcconfig (including the 'com.example' copyright string).

### [platforms] Share loop uses a kali:// custom-scheme link that is not tappable in social captions, and the https Universal/App-Links path has no assetlinks.json / apple-app-site-association and points at an unowned domain
- `mobile/lib/presentation/share_to_reels_screen.dart:64`
- **Evidence:** final link = Uri(scheme: 'kali', host: 'import', queryParameters: {...}).toString();  shared as plain text in _caption(); share_config.dart still has 'static const String linkBase = https://kali.app' with NOTE 'set linkBase to the real registered domain', and no assetlinks.json / apple-app-site-association exist (grep found none).
- **Fix:** Two problems: (1) kali:// URLs are not auto-linked by TikTok/Instagram/WhatsApp captions and are stripped/unclickable by most link crawlers, so 'friend taps the reel link' fails even on Android in practice; (2) the https alternative (ShareConfig.linkBase=https://kali.app) is an unregistered placeholder with no Android assetlinks.json or iOS apple-app-site-association, so https deep links won't verify either. For launch: register a real domain, host /.well-known/assetlinks.json (Android App Links, autoVerify) and /.well-known/apple-app-site-association (iOS Universal Links), declare applinks: associated-domains + android:autoVerify intent-filter, and have the landing page fall back to the store URL when the app isn't installed. Reconcile share_config.dart (https) with deep_link_service.dart (kali://) so producer and consumer use the same format.

### [platforms] Android ships usesCleartextTraffic=true app-wide and release builds are signed with the debug keystore — insecure transport + non-distributable signing
- `mobile/android/app/build.gradle.kts:33`
- **Evidence:** release { signingConfig = signingConfigs.getByName("debug") } with comment 'TODO: Add your own signing config'; AndroidManifest.xml line 7: android:usesCleartextTraffic="true".
- **Fix:** Two launch issues: (1) a release APK/AAB signed with the debug keystore cannot be published to Google Play and has no stable upload identity — create a real release keystore + signingConfig before launch. (2) usesCleartextTraffic=true globally permits plain HTTP everywhere because the app talks to the desktop over http://<ip>:3006; once a cloud backend exists this should be HTTPS, and cleartext should be narrowed via a network-security-config that whitelists only RFC1918 LAN ranges rather than enabling cleartext app-wide.

### [security] Sandbox network whitelist is dead code — first-party agents call the network directly via urllib/requests, bypassing the proxy entirely
- `kernel/sandbox/network_proxy.py (+ agents/*/agent.py):network_proxy.py:107 (handle); agents/weather/agent.py:79, agents/github/agent.py:71, agents/telegram/agent.py:80, agents/news/agent.py:69`
- **Evidence:** agents/weather/agent.py:79 `with urllib.request.urlopen(url, timeout=10) as resp:` (same pattern in github/telegram/news/currency/notion/todoist/messenger-hub/web-surfer); grep shows `NetworkProxy.handle()` is constructed at main.py:290 and stored on app.state but never invoked anywhere.
- **Fix:** Route all agent egress through NetworkProxy.handle() (per-agent domain whitelist + SSRF private-IP block + rate limit), or remove the proxy and stop claiming a network sandbox. As shipped, the manifest `network.domains` whitelist constrains nothing for the bundled agents.

### [security] Wildcard CORS (allow_origins=["*"]) with allow_credentials on an unauthenticated API
- `kernel/main.py:55, 612`
- **Evidence:** main.py:55 `_DEFAULT_CORS_ORIGINS = ["*"]`; 612-613 `allow_origins=_cors_origins(), allow_credentials=True`.
- **Fix:** Any web page the user visits can script requests to http://localhost:3006/chat, /settings, /skills/install while the port is open. Restrict allow_origins to the Tauri shell origin (tauri://localhost) + the Vite dev origin; never combine `*` with credentials. Remove `*` from the default list.

### [security] Third-party IP leak: 'JARVIS from Iron Man — Tony Stark’s AI butler' sent to ElevenLabs as a voice-clone description
- `kernel/voice/tts_engine_elevenlabs.py:197-198`
- **Evidence:** tts_engine_elevenlabs.py:197 `"name": "JARVIS_KALI",` / 198 `"description": "JARVIS from Iron Man — Tony Stark's AI butler",` posted to https://api.elevenlabs.io/v1/voices/add.
- **Fix:** Remove the Marvel/Disney-trademarked strings (JARVIS, Iron Man, Tony Stark) from the cloned-voice name and description sent to an external provider — this creates a written record of cloning a trademarked character voice. MEMORY already flags Marvel licensing risk for public launch; this string makes it concrete. Use a neutral name like "KALI_voice".

## MEDIUM (10)

### [build] DiskSpanning multi-file installer (.exe + .bin slices) — 'miss a .bin, install fails halfway' footgun
- `scripts/installer_premium.iss:35`
- **Evidence:** installer_premium.iss:35-36 `DiskSpanning=yes` / `DiskSliceSize=2100000000`; build_installer_premium.bat:64-73 warns users must "Share ALL of these files together" and the friend must download every .bin to the same folder.
- **Fix:** The DiskSpanning split (.exe stub + -2.bin + -3.bin, ~4.94 GB total) was a workaround for the retired 32-bit 7z SFX 4 GB limit — InnoSetup's own 64-bit compiler has no such limit. Distributing 3-4 separate files via Drive/Telegram to non-tech users guarantees a cohort that downloads only the .exe and gets a half-broken install. Collapse to a single-file installer: remove DiskSpanning/DiskSliceSize and produce one signed .exe, hosted on a CDN with HTTP range/resume so the large single file survives flaky connections.

### [build] Auto-updater declared but inert — placeholder pubkey + unprovisioned endpoint + plugin not wired
- `src-tauri/tauri.conf.json:57`
- **Evidence:** tauri.conf.json:57 `"pubkey": "dGVzdF9wdWJrZXlfcGxhY2Vob2xkZXI="` (base64 = `test_pubkey_placeholder`), endpoint `https://api.kali-os.com/updates/...`; lib.rs registers only tauri_plugin_shell + tauri_plugin_global_shortcut (no tauri_plugin_updater), and Cargo.toml has no updater crate.
- **Fix:** The updater config is non-functional: no plugin in Rust deps/registration, a placeholder signing key, and an endpoint pointing at an unprovisioned domain. Result: every new version = re-ship ~5 GB by hand to every user, and the shipped config advertises an update channel that does nothing. Either remove the dead `updater` block from tauri.conf.json until it's real, or implement it fully (add tauri-plugin-updater to Cargo.toml + lib.rs, generate a real keypair via `tauri signer generate`, provision api.kali-os.com). Do not ship a config pointing at a domain you don't control.

### [build] Dead-weight ggml-base.bin (147 MB) shipped in bundle — wrong format, referenced nowhere
- `dist_premium/premium_stage/models/ggml-base.bin:n/a (staged artifact, 147,951,465 bytes)`
- **Evidence:** `ls dist_premium/premium_stage/models/` shows `ggml-base.bin` (147 MB); grep for `ggml` across config/, kernel/, src-tauri/src/ returns nothing — STT uses faster-whisper (CTranslate2 `model.bin`), not whisper.cpp ggml format.
- **Fix:** ggml-base.bin is a leftover whisper.cpp/whisper-rs model from the abandoned Rust-native STT path (stt.rs:3-12 documents whisper-rs was dropped for faster-whisper). It is never loaded by the shipped code and adds ~148 MB of dead weight to every installer slice. Remove it from premium_stage/models/ before packaging. Also dedupe the two silero VAD files (models/silero_vad.onnx vs _internal/faster_whisper/assets/silero_vad_v6.onnx) — confirm which the active path loads.

### [build] premium_stage assembly is manual (xcopy in echo text, not scripted) — frozen-build vs source drift risk
- `scripts/build_installer_premium.bat:23`
- **Evidence:** build_installer_premium.bat:23 only *prints* the staging command as guidance — `echo Then stage: xcopy /E /I /Y dist_premium\kali-backend dist_premium\premium_stage\kali-backend`; nothing copies the freshly built kali-backend or kali-desktop.exe into premium_stage automatically.
- **Fix:** The installer packages whatever is already in premium_stage/, but copying the freshly-built kali-backend AND the release kali-desktop.exe into the stage is a manual step a human must remember. A rebuilt backend or shell that isn't re-staged ships stale bits into a signed installer with no warning. Script the staging (robocopy/xcopy kali-backend + kali-desktop.exe + install-webview2.ps1 into premium_stage) as an explicit, fail-fast step inside the .bat before materialize_hf_symlinks.py and iscc, so the packaged build always reflects the latest compile.

### [frontend] Four app modes are rendered but unreachable from any navigation (dead UI, including a 385-line audit screen that hits the backend)
- `C:/Users/User/Desktop/Jarvis/ui/src/App.tsx:128-133`
- **Evidence:** {mode === "agents" && <AgentPanel />} ... {mode === "nightstand" && <Nightstand />} ... {mode === "activity" && <SandboxActivity />} ... {mode === "canvas" && <Canvas />}
- **Fix:** ModeSelector.tsx (lines 8-14) only exposes focus/dashboard/store/settings (+showcase dev-only), and a full grep of setMode() across ui/src shows the only other targets are 'builder' (AgentStore/CuratedStore) and 'focus'/'store' (Dashboard). Nothing ever sets mode to agents, nightstand, activity, or canvas. Their content is already reached elsewhere (Dashboard embeds ActivityWidget + CanvasSection per the ModeSelector comment), so these standalone modes are dead. Delete the four unreachable branches in App.tsx plus the AppMode union entries in stores/appStore.ts and the now-orphaned imports — or, if intended, add them to ModeSelector. Note SandboxActivity still fires api.sandboxHealth/Stats/Audit on a screen no user can open.

### [frontend] English copy on the primary chat surface in an otherwise Russian, non-tech-targeted app
- `C:/Users/User/Desktop/Jarvis/ui/src/components/Chat/ChatInput.tsx:143`
- **Evidence:** addMessage("assistant", "Connection error. Is the kernel running?", "error");
- **Fix:** This is the main 'focus' screen (default mode). The user-visible error and the input placeholders are English while the rest of the app is Russian (App.tsx shows 'Джарвис думает…', kernel banner in Russian, etc.). Translate: line 143 error string, and line 318 placeholder ('Listening...' / 'Ask KALI anything...'), plus the title strings on lines 292/307 ('Stop listening', 'Start JARVIS voice'). For the строитель/врач/офисник audience an English fault message is a launch blocker for polish; fix at minimum the line-143 error and line-318 placeholder.

### [hardcodes] Share deep-link host is the parked, unowned domain kali.app
- `C:/Users/User/Desktop/Jarvis/mobile/lib/core/share_config.dart:14`
- **Evidence:** static const String linkBase = 'https://kali.app';
- **Fix:** kali.app is a parking page not owned by the project (per docs, 302 -> fortune.domains). The UGC share loop is the core distribution mechanism, so a shared https link to a non-owned domain breaks the "friend without the app" install path entirely. Acquire a real domain, set linkBase, register an https App Link / Universal Link with android:autoVerify, and host /.well-known/assetlinks.json. Until then only the kali://import custom scheme works (installed users only).

### [hardcodes] Mobile app is hardcoded to plaintext LAN backend (http/ws ://$ip:3006) with no cloud/relay
- `C:/Users/User/Desktop/Jarvis/mobile/lib/core/http_client.dart:20`
- **Evidence:** return 'http://$ip:3006$path';  (also websocket_client.dart:34 ws://$ip:3006/ws; chat_screen.dart:77, agent_store_screen.dart:132/317, settings_screen.dart:67, deep_link_service.dart:75 all hardcode http://$ip:3006)
- **Fix:** Every mobile network call targets a user-typed LAN IP over cleartext HTTP/WS on port 3006; there is no cloud backend. A store-published mobile app cannot function standalone — it only works while on the same LAN as the user's running desktop. For a public mobile launch, provision an https relay/API and route through it (or scope the launch to desktop-only and pull the mobile store listing). Centralize the base URL so cloud vs LAN is one switch.

### [hardcodes] Android manifest enables cleartext (unencrypted HTTP) traffic app-wide
- `C:/Users/User/Desktop/Jarvis/mobile/android/app/src/main/AndroidManifest.xml:7`
- **Evidence:** android:usesCleartextTraffic="true"
- **Fix:** This permits all plaintext HTTP (chat content, agent bundles, config including tokens flow over http://$ip:3006 in cleartext). Required today only because the backend is LAN HTTP. For launch, move to https and remove this flag, or restrict cleartext to specific local IPs via a networkSecurityConfig domain-config. Shipping a public app with global cleartext exposes user data on shared/hostile networks.

### [security] Cleartext HTTP/WebSocket between mobile app and backend carries chat, config writes and skill installs unencrypted over WiFi
- `mobile/lib/core/http_client.dart / websocket_client.dart / deep_link_service.dart:http_client.dart:20; websocket_client.dart:34; deep_link_service.dart:75`
- **Evidence:** websocket_client.dart:34 `final wsUrl = Uri.parse('ws://$ipAddress:3006/ws');`; deep_link_service.dart:75 `'http://$ip:3006/skills/install-bundle'` with `'overwrite': true`.
- **Fix:** On a shared/hostile WiFi, a MITM can read all chat/voice transcripts and config, and inject a malicious skill via /skills/install-bundle. Move the LAN channel to TLS (self-signed cert pinned at pairing) and authenticate the channel; at minimum require the pairing token on install-bundle.

## LOW (16)

### [build] tauri.conf bundle target is 'msi' while the shipped artifact is InnoSetup; stale installer_lite.nsi is a parallel pipeline
- `src-tauri/tauri.conf.json:35`
- **Evidence:** tauri.conf.json:35 `"targets": ["msi"]` but the real distributable is the InnoSetup DiskSpanning .exe (installer_premium.iss); separately scripts/installer_lite.nsi:8 still builds `KALI-Lite-Setup-0.2.0-beta.exe` referencing `..\src-tauri\target\release\kali-desktop.exe` and `..\dist_lite\kali-backend`.
- **Fix:** Two cleanups to avoid shipping the wrong bits: (1) the Tauri `bundle.targets:["msi"]` produces an MSI the team does not actually distribute (and which the inert updater can't service anyway) — set it to the bundle you ship or document why MSI is generated. (2) installer_lite.nsi is a separate NSIS pipeline (admin-scope, DisplayVersion `0.2.0-beta-lite`) that the premium .nsi was already retired in favor of (commit 1ed099a); confirm Lite is still an intended SKU or retire it too, so there's a single authoritative installer pipeline.

### [correctness] UI modes 'agents' and 'nightstand' are rendered but completely unreachable (no nav button, no setMode call, no hotkey, no backend event) — dead/invisible features
- `ui/src/components/Layout/ModeSelector.tsx:8-14`
- **Evidence:** modes = [{id:"focus"...},{id:"dashboard"...},{id:"store"...},{id:"settings"...},{id:"showcase",devOnly:true}] — no 'agents' or 'nightstand' entry
- **Fix:** App.tsx:128-129 renders `mode === "agents" && <AgentPanel />` and `mode === "nightstand" && <Nightstand />`, and both are valid AppMode values (appStore.ts:3-13), but a full-repo grep for setMode shows the only navigation targets are 'focus','store','builder' (AgentStore.tsx:396, CuratedStore.tsx:11, Dashboard.tsx:38/158). There is no ModeSelector button, no keyboard shortcut (ChatInput/OnboardingRoot/VoiceBuilder keydown handlers do push-to-talk/escape only), and websocket.ts onmessage has no 'ui.*' case so the backend cannot drive mode either (despite main.py:454 forwarding ui.* events). AgentPanel and Nightstand are therefore reachable only in tests. Decide per feature: either add a nav affordance (or wire a backend ui.mode event + onmessage case) to expose them, or delete the dead mode branches, the AppMode union members, and the unused AgentPanel/Nightstand imports to stop shipping invisible code.

### [correctness] WebSocket reconnect loop leaks: onclose always schedules a reconnect with no clearTimeout, and the cleanup close() itself fires onclose → zombie reconnects + duplicate sockets
- `ui/src/api/websocket.ts:84-91`
- **Evidence:** ws.onclose = () => { ...setKernelConnected(false); setTimeout(connect, 3000); }; ... return () => wsRef.current?.close();
- **Fix:** The cleanup `wsRef.current?.close()` triggers the same `onclose` handler, which schedules `setTimeout(connect, 3000)` — so after unmount (or any effect re-run; React 19 StrictMode double-invokes effects in dev, and the deps array on line 92 can re-run it) a new socket is created on a component that is gone, and pending reconnects are never cancelled. Over a session this accumulates duplicate live WebSockets all pushing into the same Zustand stores. Fix: add an `let closedByUnmount = false` (or a ref) guard; in cleanup set it true, `clearTimeout` the pending reconnect handle, and `wsRef.current?.close()`; in `onclose` skip scheduling when the flag is set. Store the timeout id so it can be cleared.

### [correctness] 'activity' standalone mode (SandboxActivity) is rendered as an AppMode but is unreachable — confirms prior incident where headless tests passed on a nav-invisible surface
- `ui/src/App.tsx:131`
- **Evidence:** {mode === "activity" && <SandboxActivity />}
- **Fix:** `activity` is a valid AppMode and renders SandboxActivity, but there is no ModeSelector button and no setMode("activity") anywhere (the ModeSelector comment states Активность was absorbed into Сводка via ActivityWidget). This is exactly the trap recorded in project memory (16 headless tests green on the nav-unreachable SandboxActivity while the live ActivityWidget was the real surface). If SandboxActivity is superseded by Dashboard's ActivityWidget, remove the dead `mode === "activity"` branch + the `activity` AppMode member + the SandboxActivity import so the codebase doesn't carry two divergent Activity views (one tested, one shipped). Same applies to the standalone `canvas` mode (App.tsx:133): CanvasSection is embedded in Dashboard (Dashboard.tsx:178) and there is no setMode("canvas").

### [correctness] Native agent subprocess opens stderr=PIPE but never drains it — large stderr output can fill the OS pipe buffer and deadlock the agent
- `kernel/agent_runtime/protocols/native.py:40-47`
- **Evidence:** self._process = await asyncio.create_subprocess_exec(... stderr=asyncio.subprocess.PIPE) — _send() only reads stdout, stderr is never consumed
- **Fix:** _send() reads only stdout.readline(); nothing ever reads self._process.stderr. A user-created or community agent that logs verbosely to stderr will fill the pipe buffer (~64KB on Windows), block on its next write, stop responding on stdout, and hit the 10s readline timeout — looking like a hung agent. Either set `stderr=asyncio.subprocess.STDOUT` is unsafe (corrupts JSON-RPC), so instead spawn a background task per process that continuously drains stderr (e.g. `asyncio.create_task` reading lines and logging them), or redirect stderr to DEVNULL/a log file. This matters at public launch because agents are user-generated.

### [correctness] Onboarding gate fails closed on a slow/erroring kernel — first launch can get stuck on the splash if the status fetch never resolves
- `ui/src/App.tsx:43-64`
- **Evidence:** if (onboardingLoading) { return ( ...«Джарвис запускается…»... ) }
- **Fix:** App renders a full-screen blocking splash while `useOnboardingGate()` is loading, with only a `slow` hint after a delay and no terminal fallback. Read ui/src/hooks/useOnboardingGate.ts to confirm the loading flag is cleared on fetch error/timeout (catch path), not just on success. On a first launch where the backend is still importing torch/voice models (main.py:402-426 can take a while) or the status endpoint errors, a gate that only clears on a successful response will leave non-tech users staring at the splash indefinitely. Ensure the gate resolves to a usable state (show onboarding or main UI with the offline banner) on timeout/error, and verify in the live app with the backend slow/stopped — not only via mocked tests.

### [correctness] ToolDispatcher reaches into AgentRuntime private state (_agents) to decide auto-load, bypassing the public liveness check — divergent 'is loaded' logic
- `kernel/agent_runtime/dispatcher.py:36-38`
- **Evidence:** if agent_name not in self._runtime._agents:  logger.info("Auto-loading agent '%s'..."); await self._runtime.load_agent(agent_name)
- **Fix:** The dispatcher checks membership in the runtime's private `_agents` dict to decide whether to auto-load. runtime.is_running (native.py:34) is process-liveness-based; a crashed/exited subprocess can still be present in `_agents` (it is only removed by unload_agent, runtime.py:102). So a dead agent passes the dispatcher's 'already loaded' check and the subsequent runtime.dispatch() raises a confusing 'not loaded'/closed-stdout error instead of being transparently restarted. Expose a public `runtime.is_loaded(name)`/`ensure_loaded(name)` that also re-spawns when the protocol reports not running, and call that here instead of touching `_agents`.

### [frontend] Builder.tsx component is dead code (not imported anywhere, superseded by VoiceBuilder)
- `C:/Users/User/Desktop/Jarvis/ui/src/components/Builder/Builder.tsx:12`
- **Evidence:** export function Builder() {  // grep for `import .* Builder/Builder` and `<Builder` across ui/src = 0 matches
- **Fix:** The voice builder flow lives in components/VoiceBuilder/ (reached via mode 'builder' -> VoiceBuilderScreen). This older text-based Builder is never imported or rendered. It also still calls api.builderClassify/builderCreateSkill and contains English UI copy ('Create Agent or Skill', 'Analyze'). Delete components/Builder/Builder.tsx (and drop the unused builderClassify/builderCreateSkill from api/client.ts if nothing else uses them).

### [frontend] WebSocket reconnect timer is never cleared on unmount, leaking an orphan socket
- `C:/Users/User/Desktop/Jarvis/ui/src/api/websocket.ts:84-91`
- **Evidence:** ws.onclose = () => { useAppStore.getState().setKernelConnected(false); setTimeout(connect, 3000); }; ... return () => wsRef.current?.close();
- **Fix:** The cleanup calls wsRef.current?.close(), which fires onclose, which schedules setTimeout(connect, 3000). That reconnect runs ~3s after unmount with no guard, reopening a socket that is never closed (and, on repeated mounts/HMR, compounding reconnect loops). Track the timer id and a 'closed-by-cleanup' flag: store the setTimeout handle, clearTimeout it in the cleanup, and skip scheduling a reconnect when the effect has been torn down.

### [frontend] Standalone Canvas() full-page mode export is dead (only CanvasSection is used)
- `C:/Users/User/Desktop/Jarvis/ui/src/components/Canvas/Canvas.tsx:132`
- **Evidence:** export function Canvas() {   // Dashboard imports { CanvasSection }; App.tsx renders <Canvas/> only under the unreachable mode 'canvas'
- **Fix:** Canvas() is rendered solely by App.tsx's unreachable `mode === "canvas"` branch; the live widget grid users actually see is CanvasSection embedded in Dashboard.tsx (line 178). Once the dead 'canvas' mode is removed, delete the Canvas() wrapper too and keep only CanvasSection. Its English header literal ('Canvas', line 141) also wouldn't match the Russian UI.

### [frontend] Dead components AgentPanel and Nightstand ship untranslated English UI
- `C:/Users/User/Desktop/Jarvis/ui/src/components/Nightstand/Nightstand.tsx:34`
- **Evidence:** {time.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })} ... 'Sleep well' (line 41); AgentPanel.tsx: 'Agents'/'No agents registered' (lines 36,41)
- **Fix:** Both are only rendered under the unreachable 'nightstand'/'agents' modes (see App.tsx finding) and were never localized (en-US date, English strings) — strong signal they are abandoned. Delete them with the dead modes. If Nightstand is a planned feature, it must be wired into navigation and localized (ru-RU date) before launch, not left as orphaned English UI.

### [frontend] Legacy wsUrl export and several catalog API methods are unused (dead code in the API layer)
- `C:/Users/User/Desktop/Jarvis/ui/src/api/client.ts:59-66`
- **Evidence:** skills: () => fetchJSON<any[]>("/skills"), catalogSearch: ... catalogTrending: ... catalogPack: ...  // commented 'Legacy Catalog / Store (kept for backward compat)'
- **Fix:** A grep shows api.catalogSearch/catalogTrending/catalogPack and the legacy runtime.ts `wsUrl` export have no callers outside their own tests (the Store uses the new skillsCatalog* endpoints). These also use `any[]`/`any` return types, weakening type safety. Either remove the legacy block (and the wsUrl rollback export if the Rust cutover is final) or document why backward-compat must persist into public launch; carrying dead, untyped endpoints into prod is avoidable risk.

### [hardcodes] Tauri updater endpoint points at unowned domain api.kali-os.com
- `C:/Users/User/Desktop/Jarvis/src-tauri/tauri.conf.json:55`
- **Evidence:** "https://api.kali-os.com/updates/{{target}}/{{current_version}}"
- **Fix:** Do not ship a config pointing at an unprovisioned/unowned domain. Either provision the real update host and pin it here, or remove the updater block until §distribution is built. If api.kali-os.com is later registered by a third party, an enabled updater would fetch updates from an attacker-controlled host. Currently inert (plugin not wired) which caps the severity at medium.

### [platforms] iOS registers no URL scheme (no CFBundleURLTypes) — the shared kali://import deep link cannot open the app on iPhone, breaking the entire share->install loop on iOS
- `mobile/ios/Runner/Info.plist:4`
- **Evidence:** grep 'CFBundleURLTypes|CFBundleURLSchemes' mobile/ios/Runner/Info.plist -> NONE (no custom URL scheme registered on iOS); meanwhile share_to_reels_screen.dart builds Uri(scheme:'kali', host:'import', ...) and deep_link_service.dart only listens for uri.scheme=='kali'.
- **Fix:** Android declares the kali://import intent-filter (AndroidManifest.xml line 39) but iOS has no equivalent. Without a CFBundleURLTypes entry declaring the 'kali' scheme in mobile/ios/Runner/Info.plist, tapping a shared kali://import?... link on iOS does nothing — the UGC import loop is 100% broken on iPhone. Add CFBundleURLTypes with CFBundleURLSchemes=['kali']. (Better: also move to https Universal Links, see next finding.)

### [platforms] Primary KALI desktop (Tauri) has no macOS build target — only Windows MSI; there is no shippable macOS desktop
- `src-tauri/tauri.conf.json:35`
- **Evidence:** "targets": ["msi"]  (bundle.windows.nsis only; identifier com.kali.desktop; resources reference ../dist/kali-backend built by PyInstaller on Windows). No macos block, no app/dmg target.
- **Fix:** The desktop backend that mobile depends on is packaged Windows-only (Tauri targets=['msi'], NSIS installer scripts under scripts/build_installer_premium.bat). If macOS desktop support is in scope for launch, add macOS bundle targets ('app','dmg'), a macOS code-signing + notarization pipeline, and a macOS PyInstaller backend build. If macOS desktop is NOT in scope, this should be an explicit launch-scope decision because the Flutter macOS target above implies macOS support that the backend can't satisfy.

### [security] Live API key fragment committed in a tracked doc (key-prefix + suffix disclosed)
- `docs/handoffs/2026-05-18-smoke-test-guide.md:138`
- **Evidence:** git grep (tracked) hit: `docs/handoffs/2026-05-18-smoke-test-guide.md:138: Should be \`sk-proj-...DFMA\`.` — the suffix `...DFMA` matches the live OPENAI_API_KEY in .env (ends `...DFMA`).
- **Fix:** The full live key lives only in the gitignored .env (good), but this doc commits its tail and confirms its identity. Rotate the OpenAI key before public launch regardless, and scrub real key fragments (and the `%APPDATA%\KALI\.env (sk-proj-...)` note in .claude/handoffs/2026-04-22-voice-fixes-and-roadmap-lock.md:46) from tracked files.
