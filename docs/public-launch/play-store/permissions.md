# KALI Mobile — Android Permissions Justification (for Play review)

> **STATUS: DRAFT for Google Play submission.**
> Source of truth: `mobile/android/app/src/main/AndroidManifest.xml` (read 2026-06-19).
> Use this to fill the Play Console **App content → Permissions / Sensitive permissions** and the **Data safety** form, and to answer reviewer questions.

## Declared permissions — complete and exact list

The shipped manifest declares **exactly two** permissions. There are no others (no location, contacts, SMS, storage, camera, Bluetooth, or background-location).

| Permission | Manifest line | Protection level | Sensitive per Play? |
|---|---|---|---|
| `android.permission.INTERNET` | `AndroidManifest.xml:2` | Normal | No (not a runtime/sensitive permission) |
| `android.permission.RECORD_AUDIO` | `AndroidManifest.xml:3` | Dangerous (runtime) | **Yes** — microphone is a sensitive permission |

> Implicit permission note: declaring `RECORD_AUDIO` causes the framework to add `android.permission.MODIFY_AUDIO_SETTINGS` implicitly on some devices. If it surfaces in the Play Console permissions view, it is a side effect of microphone capture and needs no separate user-facing justification.

There are **no** `<uses-feature>` hardware-requirement entries; the app does not force-require a microphone at the Play-filtering level, so it still installs on devices without one (voice features simply stay unavailable).

---

## 1. `RECORD_AUDIO` (Microphone) — sensitive permission

### What we tell the user (in-app / store)
"To talk to your KALI assistant by voice."

### Play-review justification (the wording reviewers expect)

> The app uses the microphone to capture the user's speech **only while the user is actively talking to the assistant**, and streams that audio over the user's **own local network to the user's own computer** (the KALI desktop application the user has paired with). The audio is used solely to provide the core voice-assistant feature requested by the user. **No audio is sent to the developer's servers, recorded for the developer, used for advertising, or shared with third parties by the app.** Capture starts on an explicit user action and stops when the user stops; it does not run in the background and there is no background-audio or always-listening behavior in this app.

### Grounding in code (for our own audit / if reviewers ask for specifics)
- Capture is gated on the runtime permission and only starts on demand: `mobile/lib/core/audio_recorder_service.dart:22-31` (`hasPermission()` checked; `startStream(...)` only after).
- Audio format is PCM 16-bit, 16 kHz, mono — `audio_recorder_service.dart:27-31`.
- Audio is base64-encoded and sent over a WebSocket to the paired PC, frame by frame — `audio_recorder_service.dart:35-40`, target `ws://<user-PC-ip>:3006/ws` (`mobile/lib/core/websocket_client.dart:34`).
- Streaming stops on `stopRecording()` — `audio_recorder_service.dart:49-57`. No `foregroundService`/background-audio declaration exists in the manifest.
- If the user denies the permission, capture returns `false` and the app surfaces the denial; the rest of the app keeps working — `audio_recorder_service.dart:43-46`.

### Data safety form mapping
- Data type: **Audio → Voice or sound recordings.**
- Collected by us? **No** (it is processed on the user's own device/PC, not sent to the developer).
- Shared? **No.**
- Processed ephemerally? **Yes** — streamed live to the user's PC while speaking, not stored by the app for us.
- Required for app function? Optional (voice is the main feature, but the app installs and the non-voice UI runs without it).

> Honesty guard: do **not** claim the audio "never leaves the device" in absolute terms — it leaves the **phone** to reach the **user's own PC** over the LAN. The accurate framing is "not sent to us / not collected by the developer." The privacy policy uses that exact framing.

---

## 2. `INTERNET` (Network access) — normal permission

### What we tell the user
"To connect to your KALI computer on your network."

### Play-review justification

> The app uses network access to communicate with the **user's own KALI desktop application** on the user's local network (LAN/Wi-Fi) — sending voice and commands and receiving responses. The app has **no backend service of its own and no developer-operated server**; it does not transmit user data to the developer. Any communication with an external third-party AI or voice provider happens **on the user's PC** and only if the user has configured that provider with their own credentials — it is not initiated by this mobile app. `INTERNET` is the standard Android permission required to open any network socket, including a connection to a device on the same local network.

### Grounding in code
- The connection target is a **user-supplied PC IP**, which defaults to none until the user sets it — `mobile/lib/core/config.dart:3` (`serverIpProvider` initial value `null`).
- Transport endpoints are all the paired PC on port 3006: WebSocket `ws://<ip>:3006/ws` (`websocket_client.dart:34`) and HTTP `http://<ip>:3006/...` for agent export/import (`mobile/lib/presentation/share_to_reels_screen.dart:59`, `mobile/lib/core/deep_link_service.dart:75`).
- No analytics/telemetry/crash SDK is present that would open its own network connections — `mobile/pubspec.yaml` (no Firebase/Sentry/Amplitude/PostHog).
- Cleartext is allowed for the LAN connection — `AndroidManifest.xml:7` (`android:usesCleartextTraffic="true"`). This is why: the local phone↔PC channel is plain HTTP/WebSocket on the LAN, not TLS. (Privacy policy discloses this and advises trusted networks.)

### Data safety form mapping
- `INTERNET` itself is not a "data type"; declare data types by what is actually sent. For this app, network traffic carries the items in §1 and the agent bundles the user explicitly shares/imports — all to the user's own PC, none to the developer.

---

## 3. Permissions the app deliberately does NOT request (state if asked)

To reassure reviewers and users, the app does **not** request any of the following (verified absent from `AndroidManifest.xml`):

- Location (`ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` / background location) — **not requested.**
- Contacts (`READ_CONTACTS`), SMS (`READ_SMS`/`SEND_SMS`), Call log — **not requested.**
- Storage (`READ/WRITE_EXTERNAL_STORAGE`, `READ_MEDIA_*`) — **not requested.** Agent sharing uses the system share sheet, which needs no storage permission.
- Camera (`CAMERA`) — **not requested.** (QR codes are *generated* for display, not scanned by the app's camera.)
- `QUERY_ALL_PACKAGES` — **not requested.** The manifest's only `<queries>` entry is the standard Flutter `PROCESS_TEXT` text-intent visibility (`AndroidManifest.xml:54-59`), not broad package visibility.
- Background execution / foreground-service / `RECEIVE_BOOT_COMPLETED` — **not requested.** No always-on listening.

---

## 4. Deep-link intent filter (not a permission, but reviewers may ask)

The manifest registers a custom-scheme intent filter `kali://import` (`AndroidManifest.xml:35-40`) used by the UGC share loop: a friend taps a shared link and the app installs the shared agent **peer-to-peer, via the user's own PC** (`mobile/lib/core/deep_link_service.dart:57-95`, which POSTs to the paired PC's `/skills/install-bundle`).

- It is a **custom scheme** (`kali://`), **not** an `http(s)` App Links host, so it does **not** require `android:autoVerify` or a hosted `assetlinks.json`. (`https` App Links are a future item; the domain is not yet provisioned — `mobile/lib/core/share_config.dart:14`.)
- This filter grants no Android permission and exposes no sensitive capability; it only lets the OS route a `kali://import` link to the app.
- Aligns with the project's anti-pivot rule: sharing/installing uses the OS and a P2P link, **never** per-platform OAuth or a developer API.

---

## 5. Quick answers for the Play Console forms

- **Does the app access sensitive permissions?** Yes — microphone (`RECORD_AUDIO`). Justification: §1.
- **Does the app use location in the background?** No.
- **Does the app have ads?** No.
- **Does the app collect or share user data (developer-side)?** No — see Data safety mapping in §1/§2; data goes to the user's own PC, not to the developer.
- **Does the app have a login?** No.
- **Foreground service?** No.

---

### Verification notes (remove before publishing)

- Permission set is exactly `INTERNET` + `RECORD_AUDIO` — `mobile/android/app/src/main/AndroidManifest.xml:2-3`. No other `uses-permission` lines exist in the file.
- Mic capture is on-demand, streamed to the user's PC, stoppable, non-background — `mobile/lib/core/audio_recorder_service.dart:22-57`.
- Network targets are the user-supplied PC on port 3006 only — `mobile/lib/core/config.dart:3`, `mobile/lib/core/websocket_client.dart:34`, `mobile/lib/presentation/share_to_reels_screen.dart:59`, `mobile/lib/core/deep_link_service.dart:75`.
- Cleartext LAN — `AndroidManifest.xml:7`.
- No analytics/ads SDK — `mobile/pubspec.yaml`.
- `kali://import` is a custom scheme with no `autoVerify`/assetlinks — `AndroidManifest.xml:35-40`, `mobile/lib/core/share_config.dart:14`.
