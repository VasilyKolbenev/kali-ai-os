# Mobile → market in a week (+ desktop hardening)

**Goal (Vasily, 2026-06-19):** two products market-ready in ~1 week.
**Honest framing:** in a week we can get **mobile to "moat-complete v1"**
(voice + create-by-voice + curated store + stable APK) and keep **desktop at
launch-candidate**. Full *public* readiness (UGC loop, consent-gate, offline
model bundle, license) is beyond the week — called out explicitly below, not
silently dropped.

## Current mobile state (read, not assumed)
- Flutter, sound architecture: Riverpod, go_router, freezed, l10n (RU/EN),
  custom theme. 17 dart files.
- **Works:** 5-tab nav (Dashboard/Voice/Chat/Agents/Settings), voice
  (on-device record → backend STT, backend TTS playback), text chat, basic
  agent store (install/toggle), settings (LLM/STT/TTS providers).
- **Connects:** `ws://<ip>:3006/ws` + `http://<ip>:3006/*` — manual LAN IP
  entry (debug prefill 10.0.2.2). Gets backend fixes automatically once pointed
  at the rebuilt backend.
- **Missing vs desktop:** voice agent builder, curated «Мастерская» (categories
  / honest statuses), real dashboard data (currently mock), memory UI, canvas,
  nightstand, activity.

## Scope for the week

### IN — the moat (without these mobile isn't the product)
1. **Baseline:** rebuild APK against the fixed backend; run on `kali_test_34`
   emulator; confirm what truly works on device. (De-risks everything.)
2. **Voice builder on mobile** — speak → create agent → deploy. THE wedge.
   Reuse backend `/builder/*` (already works); build the Flutter screen +
   wire voice. Biggest item.
3. **Мастерская parity-lite** — categories of life, RU benefit cards, honest
   statuses (Работает / Остановлен / Нужна настройка via `/agents/config-status`),
   1-click enable, inline key entry. Mirror the desktop curated model.
4. **Real dashboard data** — kill mock weather/budget/tasks; pull live from
   backend agents.
5. **Ship-ready APK** — fix `applicationId` (com.example → real), debug-signed
   build that installs cleanly.

### OUT — honest cut for the week (post-launch)
- Canvas widgets, Nightstand, Activity logs, dedicated memory UI (memory works
  backend-side; surfacing it is later).
- Full design polish / animation parity.

### Desktop (parallel, lighter — already demo/beta-ready)
- Freeze the verified demo build; no churn before the investor meeting.
- Quick wins only if time: weather city default from settings, metadata user_id.
- **Deferred (beyond week, real for public):** consent/dry-run gate (lock 4),
  UGC share surface, offline model bundle, CC-BY-NC license plan, metrics
  framework, `main.py` router split.

## Verification approach (the real bottleneck)
- Flutter UI can't be driven like the desktop preview. Verify via:
  - Backend calls (already green) — the data layer mobile consumes.
  - `kali_test_34` emulator (per memory: API-34, renders correctly; NOT Pixel_7)
    + `adb` for install/launch/screenshot.
  - Vasily on a real device for the final voice/mic pass.
- Each IN item ships only when seen working on the emulator or device.

## Sequence (rough, 1 FTE)
1. Day 1: baseline APK + emulator + real-state confirmation; fix applicationId.
2. Day 1–2: real dashboard data + connection polish.
3. Day 2–4: Мастер518ская parity-lite (the biggest UI port).
4. Day 4–6: voice builder on mobile.
5. Day 6–7: stabilize, on-device mic pass, ship APK.

## Risks (honest)
- A week for a 2-week-estimated port is tight; the OUT cut is what makes it fit.
  If voice-builder or Мастерская slips, ship mobile at "voice + store" and add
  builder as fast-follow rather than ship broken.
- Flutter verification is slower than desktop — budget for it.
- "Market-ready" here = solid closed-beta/launch-candidate for both, NOT the
  full public-UGC vision (that's the next horizon).
