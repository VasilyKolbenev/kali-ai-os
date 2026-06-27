# KALI Distribution Spec — Desktop + Mobile

**Status:** Draft for public-launch readiness
**Date:** 2026-06-19
**Scope:** How a non-tech user (строитель / врач / таксист) gets KALI onto their machine — desktop Windows installer and mobile Flutter app — without hitting SmartScreen walls, broken multi-file installs, or dead store links.
**Owner of decisions:** Vasily (domain, certs, accounts). This doc recommends; the human-action table at the end is the to-do list.

> **Anti-pivot guardrails honored throughout:** UGC sharing uses the **OS native share sheet** (`SharePlus.instance.share`, `mobile/lib/presentation/share_to_reels_screen.dart:100`) — never per-platform OAuth/API. On-device / local-data is the **trust MOAT**; every "download more on first run" trade-off below is weighed against keeping voice/data local for offline-capable friends.

---

## 0. Current state (verified against code, not aspiration)

> **Update 2026-06-27 (WS-5.5 / 5.6 config cleanup):** The inert `plugins.updater` block was **deleted** from `src-tauri/tauri.conf.json` — it advertised a placeholder pubkey + the **unowned** `api.kali-os.com` host while the plugin was never wired (no `tauri-plugin-updater` in `Cargo.toml`/`lib.rs`), so shipping it was a config-only risk (domain-squat → attacker update host) with zero runtime behavior. **Re-enable path (human-gated, needs the owned domain + provisioned host):** add `tauri-plugin-updater` to `Cargo.toml` + register in `lib.rs` + `tauri signer generate` a real keypair to replace the placeholder pubkey, point endpoints at the real update host, and version the **app-shell separately from the ~1.35 GB model payload** so a routine update is MBs not ~4.9 GB (see §4 below). Separately, `bundle.targets` was changed from `["msi"]` to `[]`: the shipped Windows distributable is the **InnoSetup** `.exe` (`scripts/installer_premium.iss` via `scripts/build_installer_premium.bat`), NOT a Tauri-bundler MSI — `tauri build` is run only to produce `kali-desktop.exe`, which the `.iss` then packages, so the bundler emitting a stray MSI nobody ships was misleading. The orphaned `scripts/installer_lite.nsi` (NSIS Lite SKU, never built by any active script/Makefile/CI — only stale doc references) was **retired** for a single authoritative installer pipeline.

| Dimension | Reality on disk today | Evidence |
|---|---|---|
| Desktop installer | InnoSetup DiskSpanning: `.exe` stub (4,135,680 B) + `-1.bin` (2,095,864,064 B) + `-2.bin` (2,100,000,000 B) + `-3.bin` (748,818,898 B) = **~4.94 GB** | `dist_premium/installer/` (ls verified); `scripts/installer_premium.iss:32-33` |
| Code signing | **None.** Zero `sign`/`signtool`/`certificate`/`notariz` in `scripts/*`. Signing is aspirational only. | grep `scripts/` → only unrelated scipy/diag hits; `VISION.md:80`, `VISION.md:668` |
| Auto-updater | Declared but **inert** — plugin not in deps, not wired in Rust, no `.sig` artifacts produced | `tauri.conf.json:53-58` (endpoint + placeholder pubkey `dGVzdF9wdWJrZXlfcGxhY2Vob2xkZXI=` = base64 `test_pubkey_placeholder`); no `tauri_plugin_updater` in `src-tauri/` (grep clean); `bundle.targets:["msi"]` at `tauri.conf.json:35` |
| Hosting | Manual Google Drive / Yandex.Disk links; no CDN, no versioned host | `installer_premium.nsi:3`; `scripts/build_backend_premium.py:6` |
| Voice models in bundle | F5 model (1,348,435,761 B) + `jarvis_ref_v2.wav` ship as **real files**; vocos + faster-whisper-small ship in a staged HF cache that uses **symlinks** | `dist_premium/premium_stage/models/`; `_internal/.hf_cache/hub/models--charactr--vocos-mel-24khz/snapshots/<rev>/pytorch_model.bin` is a symlink (find -type l verified) |
| Version skew | `0.2.0-beta` in `tauri.conf.json:3` + `installer_premium.iss:7`, but `0.1.0` in `Cargo.toml:3` and `installer_premium.nsi:11/90`. NSIS pipeline also ships the **superseded** `f5_russian_v4_winter.safetensors` | `installer_premium.nsi:67` (old model) vs live default `f5_russian_accent_tune.safetensors` |
| Mobile Android | `applicationId = "ai.kali.mobile"` (correct); release **signs with debug keys** (TODO); launcher label `"kali_mobile"`; namespace `com.example.kali_mobile`; only `kali://import` scheme (no https App Link) | `mobile/android/app/build.gradle.kts:22,31-33,11`; `AndroidManifest.xml:5,39` |
| Mobile iOS | Bundle id `com.example.kaliMobile`; **no** `NSMicrophoneUsageDescription` (auto-reject + first-mic crash); signing wired (Automatic); display name "Kali Mobile" already real | `project.pbxproj:385,564,586`; `Info.plist:10`; mic captured at `audio_recorder_service.dart:25-31` |
| Landing / App Links | `linkBase = 'https://kali.app'` placeholder; `kali.app` is a parking page (not owned); no `.well-known/assetlinks.json` | `share_config.dart:14`; `AndroidManifest.xml:35-40` (custom scheme only) |
| Store listings | Play / App Store URLs are placeholders "until published"; apps not published | `share_config.dart:16-19`; `pubspec.yaml:4` (v0.1.0) |

**Two findings that are bigger than packaging and gate a *commercial* launch (flagged here, owned elsewhere):**
- **GPLv3 FFmpeg** ships inside the proprietary installer — `avutil-60.dll` built `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265`, literal string `libavutil license: GPL version 3 or later`. Copyleft conflict with "Proprietary software" (`README.md:180`). 7 DLLs, no NOTICE alongside. **This is a legal blocker, not a distribution-mechanics item** — out of scope for *how to ship* but it determines *whether you may ship the current bundle commercially*. Track in the licensing workstream.
- **F5 model is CC-BY-NC-4.0** (NonCommercial) — blocks the paid product (`VISION.md:46,51`). Same: licensing workstream, not this doc.

This spec covers the **mechanics of getting bits onto a user's machine.** It assumes the two licensing blockers above are resolved in parallel (e.g. swap FFmpeg for an LGPL/MIT build or drop torchcodec's FFmpeg dependency; license/replace the voice model).

---

## 1. Desktop: the installer shape decision

The single largest funnel drop today is **SmartScreen on an unsigned ~5 GB .exe from a Drive link** — a full-screen "Windows protected your PC / Unknown publisher" interstitial that a строитель/врач/таксист will read as "this is a virus" and abandon. Signing (§2) fixes the *trust* wall; the *shape* of the installer fixes the *mechanics* wall (multi-file footgun, re-download-everything-on-update).

Three candidate shapes:

### Option A — Single-file installer (one signed .exe, everything inside)
- **What:** Collapse the DiskSpanning `.exe + 3 .bin` into one `.exe`. Requires a 64-bit installer engine (InnoSetup's compiler already produces 64-bit setup binaries; the DiskSpanning split at `installer_premium.iss:29` was a workaround for the *32-bit 7z SFX* 4 GB limit, which InnoSetup itself does not have).
- **Pros:** One file to download, one file to sign, impossible to "miss a .bin" (today's footgun — `README.txt:10-11` "If you miss a .bin file, install will fail halfway"). Best for offline friends: everything is in the box, no first-run network.
- **Cons:** ~4.9 GB single object. Some browsers/Drive resume large single files poorly; a dropped download = start over (no resumable chunking the way `.bin` slices accidentally gave you). Still re-ship the whole thing per version (until §4 auto-update lands).
- **Verdict:** **This is the recommended shape for the beta and the offline-friend story** — provided hosting (§3) is a CDN with **resumable/range** downloads so a 4.9 GB single file survives flaky connections.

### Option B — Small downloader-stub (~5–15 MB .exe pulls payload from CDN)
- **What:** Ship a tiny signed stub that downloads the model/runtime payload from CDN at install time (resumable), verifies a SHA-256 manifest, then installs.
- **Pros:** Stub is small → trivial to sign, to host, to email/Telegram, to embed in the landing page. Resumability and integrity are *yours* to control. You can swap the payload (e.g. a fixed FFmpeg build) without re-cutting the stub. Only-sign-the-stub keeps EV signing cheap per release.
- **Cons:** **Breaks the offline-friend MOAT story at install time** — a friend on a weak connection or air-gapped machine can't install. Mitigatable with an "offline full installer" alternative download (= Option A as a fallback link), but that's two artifacts to maintain. More moving parts (CDN auth, manifest, retry logic) = more to build and test before a frozen demo.
- **Verdict:** **Recommended as the post-beta default once CDN + signing are in place**, with Option A kept as the "offline / full" download. Not worth building before the investor demo.

### Option C — Lean installer + first-run model download
- **What:** Ship app + runtime in the installer (~1–2 GB), download the 1.35 GB voice model + vocos + Whisper on first launch via the existing `model_downloader.py` path (`REQUIRED_MODELS`, `kernel/model_downloader.py:21-32`).
- **Pros:** Smallest installer; defers the heaviest bytes.
- **Cons:** **Directly contradicts the offline/local-data positioning** — first run *requires* network and silently pulls ~1.8 GB. And it leans on a path the team already knows is fragile: MEMORY records "/MIR restage wipes HF cache → runtime download = distribution risk." It also re-introduces the exact failure the staged cache was meant to avoid.
- **Verdict:** **Not recommended.** Keep `model_downloader.py` as a *repair/fallback* path only (what it is today), never the primary first-run path.

### The symlink trap (applies to A and C, must fix regardless of shape)
The staged HF cache ships **symlinks**: `_internal/.hf_cache/hub/models--charactr--vocos-mel-24khz/snapshots/<rev>/pytorch_model.bin` → `../../blobs/<hash>` (verified `find -type l`). InnoSetup copies `premium_stage/*` (`installer_premium.iss:62-64`) with `ignoreversion`, and the offline gate only checks `os.path.isdir` + non-empty `os.listdir` (per MEMORY's note on `entry.py`), **not** that the symlink resolves. If symlinks don't survive the Drive download / unzip / copy, vocos and Whisper load through a **dangling link** and fail — instead of gracefully re-downloading.

**Fix (do this before any public download, independent of A/B/C):** materialize the HF cache as **real files**, not symlinks, in the staged bundle. Either (a) set `HF_HUB_DISABLE_SYMLINKS=1` / copy blobs over their snapshot links during staging, or (b) post-process `premium_stage` to dereference symlinks (`cp -rL` equivalent) before `iscc`. This is the single highest-leverage one-line-of-staging fix for "voice works on a friend's machine."

### Recommendation — Desktop installer shape
1. **Beta / investor demo:** **Option A (single signed full installer)** + the symlink fix + version-skew fix. Lowest funnel friction for non-tech, best offline story, fewest new moving parts before the frozen build.
2. **Post-beta default:** **Option B (signed stub + CDN)** as the primary download, **Option A kept as the "Offline / full install" link** on the landing for weak-connection / air-gapped friends. This is the only way to make per-version updates not mean "re-ship 4.9 GB by hand."
3. **Never Option C as primary.** Keep first-run download strictly as repair/fallback.

---

## 2. Desktop: code signing (the SmartScreen wall)

Today **nothing is signed** — not `kali-desktop.exe` (built at `installer_premium.iss:9`), not the final setup `.exe`. Every non-tech user hits the "Unknown publisher" interstitial. This is the **largest single install-funnel drop** and must be fixed before any public link goes out.

### OV vs EV certificate

| | **OV (Organization Validation)** | **EV (Extended Validation)** |
|---|---|---|
| SmartScreen | Builds reputation **over time / volume** — early users still see the warning until enough installs accrue | **Instant SmartScreen trust** — no "unknown publisher" wall from day one |
| Cost (indicative) | ~$200–400/yr | ~$300–600/yr |
| Key storage | Now also requires hardware (HSM/USB token) per CA/B Forum 2023 rules | Hardware token / cloud HSM required |
| Issuance | Org verification (days) | Stricter org verification (can take 1–3 weeks) |
| Identity shown | Publisher = your org name | Publisher = your org name |

**Recommendation: EV.** For a cold-start consumer product distributed to non-tech users who *will* abandon at a red warning, the OV "earn reputation over weeks" model is a launch killer — the early-adopter cohort (the exact people who fuel the UGC loop) eats the warning. EV's day-one SmartScreen pass is worth the premium. Use a CA that supports **cloud-HSM signing** (e.g. token-less, CI-friendly) so signing can be automated and isn't bottlenecked on a physical USB token.

### What to sign
1. **`kali-desktop.exe`** (the Tauri shell) — sign the release binary before it's staged.
2. **`kali-backend.exe`** and any first-party `.exe`/`.dll` you author under `premium_stage/` — at minimum the entry executables. (PyInstaller's bundled CPython and torch DLLs are third-party; signing the launchers + the installer is what SmartScreen evaluates.)
3. **The final setup `.exe`** (the InnoSetup output, or the Option-B stub) — this is the file the user double-clicks and the one SmartScreen judges. **Signing this is non-negotiable.**

### Mechanics
- Add a signing step **after** `iscc` (and after the Tauri build) in `build_installer_premium.bat` / a CI job: `signtool sign /fd SHA256 /tr <RFC3161-timestamp-url> /td SHA256 <file>`. **Always timestamp** so signatures survive cert expiry.
- For Option B, sign the **stub** every release (small, fast); the CDN payload is integrity-checked by SHA-256 manifest, not signed per-file.
- macOS notarization (`VISION.md:80`) is **out of scope** — no macOS build target exists today. Defer until a macOS build is actually produced.

> **Honest note:** signing does **not** fix the multi-file footgun, the version skew, or the symlink trap. It only removes the trust wall. Ship the §1 fixes *and* signing together, or a signed-but-broken multi-file install still drops users halfway.

---

## 3. Desktop: hosting (CDN / object storage)

Today: manual Drive/Yandex links (`installer_premium.nsi:3`, `build_backend_premium.py:6`); the inert updater points at the unprovisioned `api.kali-os.com` (`tauri.conf.json:55`).

### Requirements
- **Resumable / HTTP range** downloads (a 4.9 GB single file *will* get interrupted on consumer connections).
- **Versioned, canonical https paths** (`/desktop/<version>/KALI-Setup-<version>.exe`) so a link is stable and a version is unambiguous.
- **Cheap/zero egress** (large binaries × many downloads = the cost driver).
- A **public manifest** (`latest.json` with version + SHA-256 + URL) that both the landing page and the future auto-updater (§4) read.

### Options
| Host | Egress cost | Notes |
|---|---|---|
| **Cloudflare R2** | **Zero egress fees** (pay storage + ops only) | Best fit for "big binary, many pulls." Pairs natively with Cloudflare CDN. Resumable via range requests. **Recommended.** |
| Backblaze B2 | Low; **free egress via Cloudflare (Bandwidth Alliance)** | Strong alternative; slightly more setup to front with CDN. |
| AWS S3 + CloudFront | Egress $$ at scale | Works, but egress on multi-GB downloads gets expensive fast. Not recommended as primary for a free consumer binary. |

### Recommendation — Hosting
- **Cloudflare R2** behind Cloudflare CDN as the canonical release host. Layout: `releases.<domain>/desktop/<version>/KALI-Setup-<version>.exe` + `releases.<domain>/desktop/latest.json`.
- Keep a **mirror on Yandex.Disk/Drive** as a fallback link for the RU audience (some users trust a Yandex link more, and it's a free redundancy). The CDN is canonical; the mirror is a backup, not the source of truth.
- Provision the **real updater host** (replace `api.kali-os.com` placeholder) only when §4 is actually built — don't ship a config pointing at an unprovisioned domain (current state).

---

## 4. Desktop: auto-update

Today the updater is **declared but inert** (see §0). Result: **every new version = re-ship ~4.9 GB by hand** to every user. For a product that wants frequent voice/agent improvements, this is unsustainable, but it is **not a demo blocker** — defer the build until post-beta.

### When you build it
1. **Add the plugin for real:** `tauri-plugin-updater` to `src-tauri/Cargo.toml` + register in `lib.rs` (currently only `tauri_plugin_shell` + `tauri_plugin_global_shortcut` at `lib.rs:215-217`) + `UpdaterExt::check_update` on startup.
2. **Generate a real signing keypair** (`tauri signer generate`) and replace the placeholder pubkey at `tauri.conf.json:57`. The updater signature is **separate** from the Authenticode cert (§2) — both are needed.
3. **Bundle target must emit updater artifacts.** Today `bundle.targets:["msi"]` (`tauri.conf.json:35`) but the *shipped* artifact is the InnoSetup DiskSpanning build, which the Tauri updater **cannot service**. Decision required:
   - **Path 1 — Tauri-native bundle + updater** for the *app shell*, and treat the heavy model payload as a separately-versioned CDN download the shell fetches/verifies. Clean delta updates for the shell; models update independently.
   - **Path 2 — Custom updater** that checks `releases.<domain>/desktop/latest.json`, and if newer, downloads the Option-B stub and runs it. Reuses §1B + §3 infra; no Tauri-bundle migration. **Recommended** because it fits the existing InnoSetup/stub reality rather than forcing a bundle-format migration.
4. **Delta updates:** the win is *not re-downloading the 1.35 GB model* when only the shell changed. Version the model payload separately from the app shell so a shell-only update is a few MB, not 4.9 GB.

### Recommendation — Auto-update
- **Defer entirely until after the investor demo and beta.** It touches Rust + signing + bundle format and the demo runs on a frozen build.
- When built, go **Path 2** (custom check against `latest.json` + stub), versioning **app shell and model payload separately** so routine updates are small. This is the payoff that makes Option B (§1) worth it.

---

## 5. Mobile: distribution path

The install target itself is the **native share sheet** (`SharePlus.instance.share`, `share_to_reels_screen.dart:100`) feeding a **store link** — consistent with the anti-pivot. But the store links are placeholders and the apps aren't published (`share_config.dart:16-19`). The path is: **signed APK beta from the landing → Google Play → (iOS later).**

### 5.1 Android — APK beta from the landing (now → demo)
- **Build a release APK signed with a real upload key** (today `build.gradle.kts:31-33` signs release with **debug keys** — fine for `flutter run --release`, **not** distributable). Generate a keystore, wire a `signingConfigs.release`, keep the keystore + passwords **out of git** (per security rules).
- **Host the APK on the CDN** (§3) at `releases.<domain>/mobile/KALI-<version>.apk` and link it from the landing as "Установить APK (бета)". Sideload-friendly for the early UGC cohort before Play approval.
- **Polish before public APK (none block the build, all are brand hygiene):**
  - Launcher label `"kali_mobile"` → "Kali" (`AndroidManifest.xml:5`). Internal name is what строитель sees on the home screen.
  - Namespace `com.example.kali_mobile` → cosmetic; **deliberately deferred** to avoid MainActivity-move risk (`build.gradle.kts:8-10`). Play keys on `applicationId = ai.kali.mobile`, so submission is unaffected. Leave it.

### 5.2 Android — Google Play (the real install target)
Prerequisites, in order:
1. **Play Console developer account** — one-time $25, identity verification (D-U-N-S / gov ID for orgs; Google now requires verified identity for new personal accounts too). **Start this early — verification has a lead time.**
2. **Upload key + Play App Signing** — enroll in Play App Signing (Google holds the app signing key; you hold the upload key). Without a real upload key (replacing debug, §5.1) you cannot submit.
3. **Privacy policy URL** — **hard requirement.** Play rejects without it, *and* the app records audio (`RECORD_AUDIO`, `AndroidManifest.xml:3`) and holds LLM API keys, which forces a **Data Safety** declaration. **No privacy policy exists in the repo** (verified: repo-wide grep for privacy/eula/terms → zero files). This is a **blocker for Play submission**, owned by the legal/licensing workstream but called out here because it gates the mobile launch.
4. **Data Safety form** — declare mic/audio handling. The honest, MOAT-aligned answer: audio is processed for voice features; with the local-first architecture, voice/personal data stays on-device by default (state this truthfully — it's a selling point, not a liability).
5. **Content rating** (IARC questionnaire) — straightforward for a utility/productivity app.
6. **Store listing** — real screenshots, description, feature graphic. Replace the placeholder Play URL (`share_config.dart:18`) with the real listing once live.
7. **Review** — closed testing track first (invite the UGC beta cohort), then production. Budget days-to-weeks for first review.

### 5.3 iOS — later (explicitly out of near-term scope)
Two hard blockers make iOS **unshippable today**, but they **only bite if iOS is in launch scope** (it isn't, per the Android-only import loop):
- Bundle id is `com.example.kaliMobile` (`project.pbxproj:385,564,586`) — placeholder, must become a real reverse-DNS id under your Apple Developer account.
- **No `NSMicrophoneUsageDescription`** (`Info.plist`, grep clean) while mic is captured (`audio_recorder_service.dart:25-31`) → **App Store auto-reject + first-mic-access crash.** Add a purpose string before any TestFlight build.
- Signing is otherwise wired (`CODE_SIGN_STYLE = Automatic`) and display name "Kali Mobile" is real (`Info.plist:10`).
- **iOS also needs:** Apple Developer Program ($99/yr), App Store privacy nutrition labels, and a hosted **AASA** (`apple-app-site-association`) for Universal Links — none exist.
- **Recommendation: defer iOS to a dedicated milestone after Android is live.** Don't split focus before the demo.

---

## 6. Mobile: the share → install landing (App Links)

The UGC loop's "friend without the app" path needs a **verified https landing**, but today `linkBase = 'https://kali.app'` is a **parking page not owned by the project**, and only the custom `kali://import` scheme is registered (`AndroidManifest.xml:35-40`) — no `https` host with `android:autoVerify`, no `assetlinks.json`. So a shared link opens nothing for a non-installer.

This is **infra-gated, not code-gated** — the P2P import loop itself (`kali://import` → `/skills/install-bundle`) is already built end-to-end (`deep_link_service.dart:57-95`, `kernel/main.py:1961`). What's missing is the **public host** for the *deferred* install (friend doesn't have the app yet).

### Plan (post-domain-acquisition)
1. **Acquire the real domain** (Vasily's call; `kali.app` is parked/for-sale — pick an owned domain, mark as placeholder until chosen). Update `share_config.dart:14` once.
2. **Host `/.well-known/assetlinks.json`** with the app's SHA-256 signing-cert fingerprint → enables Android App Links (`autoVerify`) so an `https://<domain>/a/<slug>` link opens the app directly when installed, or the landing when not.
3. **Landing page** at `https://<domain>/a/<slug>`: detects platform, offers "Open in Kali" (if installed) or "Установить" → Play listing / APK. **No platform OAuth, no server-side account** — the page is a static redirector consistent with the anti-pivot.
4. **iOS later:** host AASA + add `applinks:` entitlement (deferred with §5.3).

### Recommendation — Landing
- **Static landing on Cloudflare Pages** (same account as the R2 CDN, §3) at the owned domain. Serves `assetlinks.json`, the `/a/<slug>` redirector, and the desktop download buttons (canonical CDN link + Yandex mirror). One domain, one Cloudflare account, covers desktop downloads + mobile App Links + the share-loop landing.
- Until the domain is owned: the QR/link is **structurally correct** (`share_config.dart` slug logic verified) — only the host needs swapping. Don't ship public share links pointing at the parked `kali.app`.

---

## 7. Version & identity hygiene (cheap, do before any public artifact)

These are small but make the difference between "looks like a real product" and "looks like a hobby build" — and one of them ships the **wrong voice model**.

| Fix | Current | Target | Evidence |
|---|---|---|---|
| Unify version | `0.1.0` (Cargo, NSI) vs `0.2.0-beta` (Tauri, ISS) | single source of truth | `Cargo.toml:3`, `installer_premium.nsi:11/90` vs `tauri.conf.json:3`, `installer_premium.iss:7` |
| Retire stale NSIS pipeline | `installer_premium.nsi:67` ships `f5_russian_v4_winter.safetensors` — the checkpoint **replaced 2026-06-11** because it ignored stress marks | delete/retire the NSI path; InnoSetup (`.iss`) is the real pipeline | live default is `f5_russian_accent_tune.safetensors` (`tts_engine_f5.py:111`) |
| Bundle identity | `com.kali.desktop` (Tauri) vs `B7A3F12E-KALI-PREMIUM` AppId (ISS) | intentional divergence is fine, but document it | `tauri.conf.json:4` vs `installer_premium.iss:12` |

**Why it matters for distribution:** if a user installs via the stale NSI artifact they get the **old voice** (the exact regression the team fixed). Retiring the duplicate pipeline removes the chance of shipping the wrong bits. The version unification makes the updater (§4) and "which version is this user on" answerable.

---

## 8. Recommended rollout sequence

1. **Pre-demo (frozen build):** Option A single-file signed installer **only if EV cert lands in time**; otherwise demo on Vasily's machine as planned (frozen build, no public download). Apply the **symlink fix** + **version/NSI hygiene** (§7) regardless — they're staging-only, low-risk.
2. **Beta (weeks after demo):** EV-signed Option A full installer on Cloudflare R2 + landing page with assetlinks; **Android APK beta** (real upload key) linked from landing; Play **closed testing** track opened for the UGC cohort; **privacy policy published** (gates both).
3. **Public (Tier 3):** Option B stub + CDN as primary desktop download (Option A kept as "offline/full"); **Play production**; custom auto-update (§4, Path 2); **iOS milestone** kicked off separately.

Blockers that **must** clear before *public* (not demo): EV signing, privacy policy/EULA, the GPLv3-FFmpeg and CC-BY-NC voice-model licensing resolutions, owned domain + assetlinks.

---

## 9. Human / infra action table

Legend: **[H]** = human decision/account/purchase (Vasily) · **[I]** = infra/build setup (can be specced/automated once the [H] dependency exists).

| # | Action | Type | Blocks | Placeholder to replace |
|---|---|---|---|---|
| 1 | Acquire **EV code-signing certificate** (cloud-HSM CA, supports CI signing) | [H] | Public desktop download (SmartScreen) | — |
| 2 | Choose + register the **real domain** (`kali.app` is parked/not owned) | [H] | App Links, landing, canonical download URLs | `share_config.dart:14` `https://kali.app` |
| 3 | Create **Cloudflare account** → R2 bucket + Pages site + CDN | [H]+[I] | Hosting, landing, App Links host | `api.kali-os.com` updater placeholder (`tauri.conf.json:55`) |
| 4 | Create **Google Play Console** account ($25, identity verification — start early) | [H] | Play submission | — |
| 5 | Generate **Android release upload keystore**; wire `signingConfigs.release`; keep out of git | [H]+[I] | Distributable APK / Play | `build.gradle.kts:31-33` (debug-key signing) |
| 6 | Publish **Privacy Policy + EULA/ToS** at the owned domain (none exist in repo) | [H] | Play submission, Data Safety, public launch | n/a (absent entirely) |
| 7 | Resolve **GPLv3 FFmpeg** conflict (swap for LGPL/MIT build or drop torchcodec FFmpeg dep) | [H]+[I] | Commercial/public distribution (legal) | `dist_premium/premium_stage/models/ffmpeg/*.dll` |
| 8 | Resolve **CC-BY-NC F5 model** license (license commercially / replace model) | [H] | Paid product (`VISION.md:46,51`) | `Misha24-10/F5-TTS_RUSSIAN` (`tts_engine_f5.py:126`) |
| 9 | **Materialize HF cache as real files** (dereference symlinks) in staging | [I] | First-run voice on friend machines (offline) | `_internal/.hf_cache/hub/.../snapshots/<rev>/*.bin` symlinks |
| 10 | **Unify version** + **retire stale NSIS pipeline** (ships old voice model) | [I] | Correct bits shipped; updater sanity | `installer_premium.nsi:11/67/90` |
| 11 | Add **signtool signing step** post-`iscc` and post-Tauri-build (timestamped) | [I] | depends on #1 | absent in `scripts/*` |
| 12 | Build **Option A single-file installer** (collapse DiskSpanning) | [I] | Multi-file footgun (`README.txt:10-11`) | `installer_premium.iss:32-33` |
| 13 | Host **`assetlinks.json`** with release-cert fingerprint at `/.well-known/` | [I] | Android App Links (depends on #2,#5) | none registered (`AndroidManifest.xml:35-40`) |
| 14 | Provision **Apple Developer Program** ($99/yr) — *iOS milestone, deferred* | [H] | iOS only | — |
| 15 | Add **`NSMicrophoneUsageDescription`** + real iOS bundle id — *iOS milestone* | [I] | iOS submission (auto-reject) | `Info.plist` (absent); `project.pbxproj:385` |
| 16 | (Post-beta) Build **Option B stub + custom auto-updater** (Path 2) | [I] | Per-version re-ship of 4.9 GB | inert updater (`tauri.conf.json:53-58`) |

---

## 10. Honest caveats

- **Signing alone is not enough.** A signed installer that still ships 4 separate files, the wrong voice model, or symlinks that dangle on a friend's machine will *still* drop users — just past the SmartScreen wall instead of at it. Ship §1+§2+§7+§9 together.
- **EV cert lead time is real** (org verification can take 1–3 weeks). If a public download is wanted soon, **start the EV application now** (action #1) — it's the long pole.
- **The two licensing blockers (GPLv3 FFmpeg, CC-BY-NC model) are not distribution mechanics but they gate a *commercial* public launch.** This spec assumes they're resolved in parallel; if they aren't, the bits you'd be signing and hosting aren't legally shippable as a paid product.
- **Offline-friend story is the MOAT's install-time expression.** Every "download more later" option (B partially, C fully) trades against it. The recommendation keeps a full offline installer (Option A) available precisely so the local-data promise holds for a air-gapped or weak-connection friend — don't let the convenience of a small stub erase that.
- **Where real values aren't chosen** (domain, cert provider, exact CDN paths, Apple/Play account ids), this doc uses clearly-marked placeholders (`<domain>`, `<version>`, `releases.<domain>/...`) rather than inventing them. Filling them is the action table above.
