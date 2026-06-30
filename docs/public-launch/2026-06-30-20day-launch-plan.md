# KALI — 20-Day Public Launch Plan (grounded)

**Date:** 2026-06-30
**Source:** grounded 8-agent re-audit (`workflow wf_ea5d0ad5-206`) + the no-legal-entity / Armenia-or-Uzbekistan constraint + the iOS-via-cloud-CI correction. Supersedes the 10-day framing of `2026-06-29-remediation-plan.md` for the launch window.

## TL;DR
- **All 4 tracks to 100% public in 20 days = no.** macOS and iOS are hardware/account-gated multi-week; macOS is honestly fast-follow.
- **Achievable in 20 days:** **Windows desktop + Android (companion + on-device standalone)** publicly, with **iOS as a stretch (TestFlight beta possible if Apple enrollment clears in time)**.
- **The new #1 long pole is the legal entity** (none yet). It gates EV-cert, Apple Developer, Play Console — all three. **Open it in Armenia, NOT RF** (RF = blocked from Apple/Google/cert/payments). Entity → then the cert/account clocks can even start.
- **Honest risk:** entity (~days–2wk) **serialized before** EV-cert (1–3wk) can push a SmartScreen-clean public Windows download past 20 days. Mitigation: ship a **trusted-installer beta** to a known cohort while the clocks run, and **auto-flip to clean public the day the cert lands** (pipeline already env-gated: signs the moment `KALI_SIGN_CERT` is set).
- **Why it felt like treading water:** external-gate-bound, not throughput-bound. The one shippable column (Windows + Android) has been near-done for days; effort spread across 3 unreachable columns (iOS/macOS/marketplace) whose clocks never started. The fix is starting the long external clocks **today** + narrowing v1 — not coding faster.

## Grounded readiness today (re-audit, not the old 2026-06-29 numbers)
| Track | Audit (06-29) | Today | Note |
|---|---|---|---|
| Windows desktop | 75% | **80%** | reel bundled, LGPL FFmpeg done; needs Tauri-exe rebuild + RTX frozen smoke |
| Android | 35% | **52%** | pairing-token + standalone Inc1+Inc2 landed; needs notification-init (FIXED today) + real-device verify + keystore |
| iOS | 60% | **58%** | Dart standalone works cross-platform; 100% Apple-account/Mac-gated |
| macOS | 25% | **30%** | config-complete (WS-4.3); no build path on Windows-only HW → fast-follow |
| Cross-cutting | — | **55%** | marketplace real-Supabase-backed, graceful-degrades with no keys (dormant by design) |
| External gates | — | **30%** | code-side inert-ready; the clocks are the gate |

## Three lanes (run in parallel)

### 🟥 Lane A — External gates (Vasily, calendar-bound) — START DAY 0
| # | Gate | ETA | Depends on |
|---|---|---|---|
| A0 | **Register LLC in Armenia** (use a local incorporation agent) | ~3 days–2 wk | — (THE new long pole; gates A1/A4/A5) |
| A1 | **EV code-signing cert** org-verification | 1–3 wk **after entity** | A0 (CA needs a real legal entity) |
| A2 | **Buy owned domain** (replace parked kali.app) | hours | — (do today; gates A3, legal URL, AASA/assetlinks) |
| A3 | **CDN** with resumable/range for ~4.9 GB installer | 1–2 days | A2 |
| A4 | **Apple Developer Program** (org, via entity) | days–2 wk | A0 (+ D-U-N-S) |
| A5 | **Play Console** account + upload keystore | days | A0 |
| A6 | **Legal Privacy/EULA** counsel review (13 placeholders + BYO-key cloud-LLM addendum) | ~7 days | A2 (public URL) |
| A7 | **Payments**: Stripe doesn't serve AM/UZ → use **Paddle/LemonSqueezy** (merchant-of-record) | days | A0 (v1 can be free — defer) |

### 🟦 Lane B — Code (me, do now; realistically code-complete ~Day 7–8)
Ordered by leverage + uncertainty (stress-critic: run the highest-uncertainty native paths FIRST):
1. **Frozen-bundle RTX smoke FIRST** (Vasily's GPU): boot `kali-backend.exe` → `GET /skills/{name}/reel` (PyAV native DLL load + font path post `--onedir`) → full F5 GPU synth on LGPL DLLs. *Highest-uncertainty item; classic PyInstaller trap; budget "1 clean day + N days DLL whack-a-mole."*
2. **Rebuild stale Tauri `kali-desktop.exe`** (Jun-25 predates Rust :3006 auth + PairPhone QR) — unblocks the whole installer chain. (0.5d)
3. ~~Android notification init~~ ✅ **DONE today** (`c89e18c` — `initializeNotifications()` + `kali_reminders` channel; was never initialized → reminders silently no-op'd on device).
4. **Build the InnoSetup installer** once both exes fresh (0.5d, pipeline never run on this branch).
5. **Two-device tethered loop** on RTX + 2nd device: create→works→share reel→import + `kali://pair` QR → authenticated :3006 chat. (1d)
6. **Standalone live-verify** on `kali_test_34` + **a real Android phone**: `kali://import` reminder → permission → notification actually **fires across an app-killed + idle window** (not just AVD). (1.5d)
7. **iOS cloud-CI** (Codemagic / GitHub macOS runner / Xcode Cloud) — build+sign `.ipa` without a physical Mac; wire once A4 (Apple account) exists. (1–2d setup)
8. **macOS notification branch** (Darwin init + macOS `NotificationDetails`) — code now so it compiles the day a Mac/CI exists; do NOT let it consume v1 throughput. (1d, fast-follow)
9. **Supabase**: apply 2 migrations + advisors + fix RLS/index + swap non-atomic `install_count` RMW for a Postgres rpc — ONLY after A-provisions a project; non-blocking fast-follow. (2d)

### 🟩 Lane C — Verification & launch (gate-bound tail)
- Legal hosted on domain; installer staged on CDN.
- **EV lands → sign → clean public Windows download** (auto-flip). Until then: trusted-installer beta to a known cohort + documented SmartScreen "Подробнее → Выполнить".
- Android: ship via **direct APK** (honest: "unknown sources" friction — the Android SmartScreen-equivalent) and/or **Play open-testing** (needs A5 + A2 + A6).
- iOS: **TestFlight beta** if A4 clears (stretch); App Store review is fast-follow.

## Day-windowed critical path (20-day frame)
| Window | Milestone | Lane |
|---|---|---|
| **Day 0** | Start Armenia LLC (A0) · buy domain (A2) · engage legal (A6) | 🟥 |
| Day 0–2 | RTX frozen smoke (B1) · rebuild Tauri exe (B2) | 🟦 |
| Day 2–4 | Build installer (B4) · CDN once domain lands (A3) | 🟦🟥 |
| Day 3–7 | Two-device + standalone real-phone live-verify (B5,B6) → **code-complete checkpoint ~Day 7–8** | 🟦 |
| Day 5–10 | Entity lands → **start EV-cert (A1)** + Apple (A4) + Play (A5) clocks · legal finalized + hosted (A6) | 🟥 |
| Day 7–12 | iOS cloud-CI wired (B7); TestFlight build if A4 cleared · macOS branch code-ready (B8) | 🟦 |
| Day 12–20 | Gate tail: CDN staged · **trusted-installer beta public** (Win + Android APK) · EV-cert lands → flip to clean signed public · iOS TestFlight (stretch) | 🟩🟥 |

## Honest 20-day verdict
- ✅ **Windows (beta→clean-on-cert) + Android (APK/open-testing): solidly achievable.**
- 🟡 **iOS TestFlight: stretch** — depends on Armenia entity → Apple enrollment → cloud-CI all clearing inside the window. App Store *production* listing: likely just past 20 days.
- 🔴 **macOS: fast-follow** (no build path without Mac/CI; not worth v1 throughput).
- ⚠️ **The serialization risk is real:** entity (≤2wk) **then** EV-cert (1–3wk) can exceed 20 days for a *clean-signed* public Windows download. The trusted-installer-beta + auto-flip decouples "public" (in-window) from "SmartScreen-clean" (cert-bound). Start A0 + A2 **today** or the whole tail slides.

## Anti-pivot check
v1 = voice-created agents + mobile + UGC (share-link/QR, no catalog dependency) + local data. No dev-integrations, no OS-assistant, no crypto. The standalone reminder runtime keeps "your agents run on your phone" literally true. Clean.
