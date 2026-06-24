# Apple platforms (iOS + macOS) & cross-platform distribution — design spec

**Status:** design (2026-06-24). Read-only artifact; no code changed.
**Scope:** how KALI ships to **Windows desktop · macOS · iOS · Android**, and how a
user finds and downloads the right build. Answers the open questions: *how do we
distribute on mobile (Android/iOS)? what about our macOS users?*
**Builds on (does not duplicate):**
- `2026-06-19-mobile-standalone-design.md` — the mobile **architecture** decision
  (Option C: on-device lite engine + a thin, opt-in cloud relay). This spec takes
  that as given and adds the **platform + distribution** layer.
- `2026-06-19-distribution-spec.md` — desktop signing/host plumbing.
- `2026-06-24-prod-readiness-audit.md` — the platform blockers cited below are its
  verified findings.

**Anti-pivot anchors (binding):** UGC via the **OS native share sheet** + `kali://`
deep links, never per-platform OAuth. **On-device / local-data is the moat** — every
tier below is judged on keeping that true.

---

## 1. The one model: two tiers, mapped to platforms

KALI is **two products that share a brain**, not four ports:

- **Heavy local desktop** — Tauri + **local Python + ML** (F5-TTS, Whisper, torch).
  Full offline voice. GPU-bound. **Windows today.**
- **Light client** — **Flutter**, the on-device **lite** orchestration engine from
  the standalone design (Option B/C): chat, template skills, builder, dashboard,
  bundle import — all on-device — with **LLM + voice delegated to the cloud** (the
  router already degrades no-GPU → cloud). One Flutter codebase serves **Android,
  iOS, and macOS**.

| Platform | Tier it ships as | Voice | Gate |
|---|---|---|---|
| **Windows** | Heavy local desktop (Tauri+Python) | **Local F5 (CUDA)** | EV cert (signing) |
| **Android** | Light Flutter client | Cloud (user key / Pro relay) | Play acct + real keystore |
| **iOS** | Light Flutter client | Cloud | **Mac + Apple Dev** |
| **macOS** | Light Flutter client **now**; heavy local desktop **later** | Cloud now → **on-device MLX-F5 later** | **Mac + Apple Dev** |

The split is deliberate: "standalone mobile/Mac" is a **re-host of light
orchestration + cloud voice**, NOT an ML port to the phone (per the standalone
design §1). The heavy local tier stays where a GPU is.

---

## 2. macOS — the actual question, answered

We have macOS users. Two honest paths; they are **sequenced, not either/or**:

### 2a. Now (1.0): macOS gets the **Flutter light client**
Same build as iOS/Android (one codebase). Cloud LLM + cloud voice + on-device-lite
orchestration. **Why this first:** it ships macOS support with **zero Mac-specific
ML work** — no PyInstaller-macOS, no torch-on-Mac, no CUDA (Macs have **no NVIDIA**,
so the Windows F5 path cannot run on a Mac anyway). A macOS user gets create-by-voice
+ run-agents immediately, cloud-backed, local-data-on-device.

### 2b. Later (2.0): full **Tauri+Python local desktop on macOS**
The heavy tier on Mac. The blocker is **voice**: F5-TTS is CUDA-only, so a Mac-local
voice needs the **on-device MLX-F5 path** — which is exactly the **F5-on-device R&D
track** (`research/on-device-tts/`, Apple-Silicon `f5-tts-mlx`). So **macOS-local
voice is gated on the F5-on-device 2.0 work**, not on porting CUDA. Until then a
Mac-local desktop would degrade voice to cloud (ElevenLabs) — at which point it
offers little over 2a. **Conclusion: do 2a for 1.0; 2b becomes worth it once
MLX-F5 lands (and is the macOS payoff of the F5-on-device bet).**

**Both macOS paths require a Mac to build/sign + an Apple Developer account** (§5).

---

## 3. iOS — light Flutter client, App-Store-bound

iOS = the light client (§1). It cannot side-load like Android, so **App Store is the
only real channel** (TestFlight for beta). Per the standalone design, on-device-lite
+ cloud voice/LLM keeps the moat. Anti-pivot share = iOS share sheet + Universal
Links (`kali://` + https deferred-link).

**Hard prereqs (audit-verified blockers, all in `mobile/ios/`):**
- Bundle id is still `com.example.kaliMobile` (`project.pbxproj`) → **rename to
  `ai.kali.mobile`** (match Android's real id) before any upload.
- **No `NSMicrophoneUsageDescription`** in `Info.plist` while the app records audio
  (`audio_recorder_service.dart`) → **auto-reject + first-mic crash.** Add it.
- No `CFBundleURLTypes` / AASA for deep links → add for the share loop.
- Signing is `CODE_SIGN_STYLE=Automatic` (fine) but needs the Apple Dev account.

---

## 4. Android — Play + direct APK

Two channels (keep both): **Play Store** (discovery, trust) **and a direct APK** from
the landing (anti-pivot fallback, app-less-friend deferred install).

**Hard prereqs (audit-verified):**
- Release build is **signed with the DEBUG keystore** (`build.gradle.kts:33`) →
  Play rejects it; generate a real **upload keystore** (custody = Vasily) first.
- `usesCleartextTraffic=true` app-wide — fine for the LAN-client phase, but the light
  client talks **https** to cloud/relay, so scope cleartext down (or remove) for the
  standalone build.
- `applicationId` is already real (`ai.kali.mobile`); internal label `kali_mobile` /
  `com.example` namespace are cosmetic (tidy for polish).

---

## 5. Distribution funnel — landing → the right build

One owned domain is the hub (today `kali.app` is **parked/not owned** — the #1 infra
gate). The drafted landing (`docs/public-launch/index.html`) becomes platform-aware:

```
<owned-domain>  →  detect OS →
   Windows  → signed InnoSetup installer (CDN / R2)        [gate: EV cert]
   macOS    → App Store (Flutter client)  → later: notarized .dmg
   iOS      → App Store / TestFlight
   Android  → Play listing  +  "direct APK" link (CDN)
   shared agent link (kali://…) → if app installed: import;
                                  else: store/desktop (deferred install)
```

- **Windows:** the ~4.2 GB DiskSpanning installer we just rebuilt → collapse to a
  single signed `.exe` once a CDN host exists (ROADMAP 1.6) and sign it (1.2).
- **macOS/iOS:** App Store is the channel; the landing deep-links to it.
- **Android:** Play + a direct APK (so the native-share `kali://` loop has a no-Play
  fallback).
- **Deferred deep link** (app-less friend) = the relay's Phase-2 job from the
  standalone design — needs the owned domain + `assetlinks.json` / AASA hosted.

---

## 6. Hard gates (what only Vasily/infra can unblock)

| Gate | Unblocks | Why only you |
|---|---|---|
| **A Mac (build machine)** | iOS, macOS (both tiers), notarization | Apple builds/signs/notarize **only on macOS** |
| **Apple Developer Program ($99/yr)** | iOS + macOS App Store, notarization, TestFlight | Account + identity vetting |
| **EV code-signing cert** | Windows installer (no SmartScreen) | Legal entity vetting |
| **Android upload keystore** | Play | Secret-key custody |
| **Google Play account** | Play listing + Data Safety | Account + declarations |
| **Owned domain + CDN/host** | Landing, deferred links, APK/installer hosting | Buy + DNS + host |
| **Privacy policy + EULA** | Any store + any cloud path | Legal text |
| **F5 license + JARVIS IP** | Pro/branded cloud voice (relay Phase 4) | License/IP calls |

**Apple-specific bottom line:** **without a Mac + an Apple Developer account, nothing
Apple (iOS or macOS) ships** — that pair is the gate for the entire Apple column.

---

## 7. Recommended sequence (design intent)

1. **1.0 desktop (Windows):** sign + host the installer (gates: EV cert, CDN). Already
   built; code-ready.
2. **1.0 mobile/macOS:** the **Flutter light client** (standalone design Phase 0+1) —
   fix the audit blockers (iOS bundle-id/mic, Android keystore), ship the on-device-lite
   engine, cloud voice/LLM. **One codebase → Android + iOS + macOS.** Gates: Apple
   Dev+Mac (iOS/macOS), Play acct+keystore (Android), domain (funnel).
3. **Relay (opt-in, phaseable):** landing + deferred deep link → cloud catalog → Pro
   voice (standalone design Phases 2–4). Gates: domain/host, then F5/IP for Pro voice.
4. **2.0 macOS-local desktop:** the heavy Tauri+Python tier on Mac, **once MLX-F5
   (F5-on-device) gives local Apple-Silicon voice.** This is the macOS payoff of the
   F5-on-device track.

---

## 8. Honest caveats

- **The light Flutter client (Option B/C) is design, not built.** Today the mobile app
  is still the thin LAN client (audit blocker: `http_client.dart:20` hardcodes
  `http://<ip>:3006`). Building the on-device-lite engine is **L–XL** (the standalone
  design's main cost) — it is the real mobile/macOS-1.0 work, not a config change.
- **macOS-local (2b) is blocked on F5-on-device (MLX).** Don't promise local Mac voice
  before that R&D lands; the M0 baseline (`research/on-device-tts/BASELINE.md`) shows
  the on-device gap is large.
- **Everything Apple is gated on a Mac + Apple Dev account** — these are the long pole
  for the entire Apple column; start them early if Apple is in 1.0 scope.
- **Anti-pivot preserved:** native share + `kali://` everywhere; the relay carries only
  bundles + metadata, never personal data; on-device-lite keeps the moat literally true.
```
