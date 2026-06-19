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

## Scope — FULL PARITY, no cuts (Vasily, 2026-06-19)

Mobile must be no less useful than desktop. Prioritized so value lands first;
nothing dropped — items lower in the list ship later in the week, not "never".

1. **Baseline** ✅ — APK builds, runs on `kali_test_34`, applicationId real.
2. **Backend bridge** ✅ — emulator → :3006 (staged desktop) → :3005; mobile
   connects and renders the live app.
3. **Real dashboard data** ✅ (backend) — `/dashboard` live from agents, honest
   «—». NEEDS frozen-backend rebuild to reach mobile (mobile still on staged
   build showing old mock).
4. **Kill remaining dashboard mockups** — the hardcoded «Jarvis Insight»
   (l10n `insightText`: «встреча через 30 минут…») and «агент готов» teaser are
   fake; wire to real briefing/agent state or remove.
5. **Мастерская parity** — categories, RU cards, honest statuses
   (`/agents/config-status`), 1-click enable, inline key entry; segments
   Мои·Витрина·Сообщество. Mirror desktop curated model.
6. **Voice builder on mobile** — speak → create agent → deploy. THE wedge.
   Reuse backend `/builder/*`.
7. **Memory** — surface facts on mobile (works backend-side; needs UI).
8. **Canvas / live widgets** — port the interactive widgets.
9. **Activity / Nightstand** — agent execution feed + ambient mode.
10. **Share-to-Reels** — currently a mockup (export button = SnackBar only);
    make the UGC export real (or honest pending-state).
11. **Ship-ready signed APK**.

> Honesty on timeline: TRUE full parity is the ~2-week estimate. In one week we
> land items 1–6 (the moat: connected, real dashboard, store, voice creation)
> well; 7–11 continue as fast-follow. No functionality is cut — sequenced.

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
