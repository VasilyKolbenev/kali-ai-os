# KALI — Public-Launch Roadmap (Desktop + Mobile)

> One sequenced plan to take KALI from a frozen investor-demo build to a
> public mass-market launch, covering **both** products. Every item is tagged
> with **effort** (S/M/L/XL) and **owner**, and split between *what we can
> build in code* and *what only a human / infra / legal can do*.
>
> **Honest horizon (vetted, unchanged):** investor demo ~90% ready ·
> closed beta ~70% · **public mass-market ~40%**. The 40% gap is not
> features — it is trust (consent + dry-run), distribution (signing, a real
> download host, store presence) and legal (privacy policy, FFmpeg GPLv3,
> F5 NonCommercial, JARVIS/Marvel IP). This roadmap closes those, in order.

- **Status anchor:** HEAD `5043831`, 45 commits ahead of `origin/main` (unpushed).
- **Scope guard:** the demo runs on a **frozen** build. Nothing here touches
  demo-critical artifacts. Sequencing assumes the demo ships first, then this
  work begins on a post-demo branch.
- **Anti-pivot (binding):** UGC sharing uses the **OS native share sheet** +
  the `kali://` scheme — **never** per-platform OAuth/API. On-device / local
  data is the **MOAT**; everything below frames it as a strength.

---

## How to read this

| Tag | Meaning |
|-----|---------|
| **Effort** S | < 1 day · **M** 1–3 days · **L** ~1 week · **XL** multi-week |
| **us-code** | We implement in this repo (Claude + Vasily reviewing) |
| **us-design** | We write a spec/contract first (design debt before code) |
| **vasily** | Only Vasily can decide/do (license call, brand call, account) |
| **infra** | Provision external infrastructure (domain, CDN, cert, host) |
| **legal** | Requires legal text/counsel (policy, EULA, IP clearance) |

**Severity** carried from the audit: `blocker` (gates the milestone) ·
`high` · `medium` · `low`.

---

# Milestone map (at a glance)

```
  M0  Pre-flight / unfreeze        — branch, push, version sanity        (days)
  M1  Closed beta (private link)   — trust gate v1 + signed installer    (~3–4 wk)
  M2  Beta hardening               — full consent/dry-run + measurement  (~3–4 wk)
  M3  Public launch (web + Play)   — host, store, legal, landing         (~4–6 wk)
  M4  Commercial / monetization    — license cleanup, iOS, Pro voice     (post-launch)
```

Milestones are **gated**: M1 cannot ship until its blockers clear, M3 cannot
ship until M1+M2 legal/trust blockers clear. Effort sums are *engineering
days*; the **human/infra/legal critical path runs in parallel and is the real
long pole** (see [§ Human-only critical path](#human-only-critical-path)).

---

# M0 — Pre-flight (unfreeze & sanity)

> Do *after* the demo, *before* any milestone work. Cheap, unblocks everything.

| # | Item | Sev | Effort | Owner | Notes / evidence |
|---|------|-----|--------|-------|------------------|
| 0.1 | Branch + push the 45 unpushed commits to `origin/main` (or a `release/0.2` branch) | — | S | vasily | HEAD `5043831`, 45 ahead, nothing pushed. Back up before any rebuild. |
| 0.2 | Reconcile version skew across packaging files | medium | S | us-code | `src-tauri/Cargo.toml:3` = `0.1.0` vs `tauri.conf.json:3` = `0.2.0-beta`; `installer_premium.nsi:11` = `0.1.0`. Pick one (`0.2.0-beta`). |
| 0.3 | Delete / quarantine the stale NSIS pipeline | medium | S | us-code | `installer_premium.nsi:67` still ships `f5_russian_v4_winter.safetensors` — the checkpoint replaced 2026-06-11 because it ignored stress marks (live default is `f5_russian_accent_tune.safetensors`, `tts_engine_f5.py:111`). InnoSetup (`.iss`) is the real pipeline; the `.nsi` is a footgun. (Audit BLD-4/BLD-7.) |
| 0.4 | Unify bundle identity | low | S | us-code | `tauri.conf.json:4` `com.kali.desktop` vs `installer_premium.iss:12` `B7A3F12E-KALI-PREMIUM`. Harmless today, confusing for updates/signing later. |

**Exit:** one canonical version string, one installer pipeline, work branched.

---

# M1 — Closed beta (private link, hand-picked testers)

> Goal: a small group of real non-tech testers (строитель/врач/таксист) can
> **install without a SmartScreen wall**, and **see what an agent will touch
> before it touches it**. This is the minimum honest bar for putting KALI on
> someone else's machine. Distribution stays a private link — no store yet.

## M1 blockers — must clear to ship the beta

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 1.1 | **Buy a code-signing certificate** (EV recommended) | blocker | — | **vasily + legal** | Nothing is signed: `grep sign\|signtool\|certificate\|notariz scripts/*` → **0 matches** (verified). EV gives **instant** SmartScreen trust; OV must earn reputation over weeks. This is the single largest install-funnel drop. |
| 1.2 | **Sign the installer + inner `kali-desktop.exe`** in the build | blocker | M | us-code (after 1.1) | Add `signtool` step to `build_installer_premium.bat` and sign `kali-desktop.exe` (`installer_premium.iss:9` builds it unsigned) + the final `-Setup.exe`. Spec: `docs/public-launch/2026-06-19-distribution-spec.md`. |
| 1.3 | **Consent disclosure v1** — show plain-language permissions before an agent gets real access | blocker | M | us-code | Today the click *is* the consent: `main.py:1013-1024` docstring says so verbatim; `PreviewConfirm.tsx:51-69` («Запустить») and `StoreCards.tsx:46-58` («Включить») show **no** permissions. Slice 1 of the gate spec: a `ConsentCard` listing capabilities, read-back via existing TTS (`PreviewConfirm.tsx:34-49`). Disclosure-only is **safe near launch**. Spec: `docs/public-launch/trust/2026-06-19-consent-dry-run-gate-spec.md`. |
| 1.4 | **Fix the staged HF-cache symlink risk** (first-run voice failure for offline testers) | blocker | M | us-code | Staged cache ships **symlinks** (`premium_stage/.../vocos/snapshots/<rev>/pytorch_model.bin -> ../../blobs/<hash>`, verified). If they don't survive copy/install, the offline gate (`entry.py:80-83`) only checks dir-non-empty, not that links resolve → vocos/Whisper load **fails through a dangling link** instead of degrading. Materialize as real files in the stage. (Memory: "bundle vocos+Whisper as real files".) |

## M1 high-value (strongly recommended for beta, not strictly gating)

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 1.5 | Replace manual Drive/Yandex link with a real download host | high | M | infra + us-code | `build_backend_premium.py:6` + `installer_premium.nsi:3` = "share via Google Drive / Yandex.Disk". No CDN, no canonical https page. Cloudflare R2 (zero egress) + resumable range. Spec §Hosting. |
| 1.6 | Collapse the multi-file DiskSpanning installer to a single artifact | medium | M | us-code | `installer_premium.iss:32-33` `DiskSpanning=yes` + 2.1GB slices → 4 files on disk (verified: `.exe` + `-1/-2/-3.bin`, ~4.94GB). `README.txt:10-11`: "All 4 files MUST sit in the same folder … miss a .bin and install fails halfway." A footgun for non-tech installs. With a CDN host (1.5) the 4GB SFX limit constraint relaxes → single signed installer. |
| 1.7 | **Android beta APK with a real upload key**, hosted on the CDN | high | M | us-code + infra | Release currently signs with **debug keys** (`build.gradle.kts:31-33`). Generate an upload keystore, host the APK next to the desktop installer. Lets mobile testers in alongside desktop. |
| 1.8 | Dry-run preview v1 at the single execution chokepoint | high | L | us-code | No dry-run anywhere: `grep dry.?run\|preview\|подтверд agents/` → 0 files; `deployer.py:49-65` registers cron for autonomous fire with no gate. Add a preview hook at `backend.py:139-140` (`execute:{action}`) / `skill_executor.py:62-84`. **Caveat:** the *gating* half needs the retest gate (M2); a *preview-only* surface (show, don't block) is safe in beta. |

**M1 engineering ≈ 2–3 weeks** once the cert (1.1) lands. **The cert + host
provisioning is the long pole, not the code.**

**Exit criteria:** a tester clicks one link, the installer is signed (no
SmartScreen interstitial), first-run voice works offline, and before any agent
acts the user sees *what it will touch*.

---

# M2 — Beta hardening (trust + measurement)

> Goal: the consent/dry-run gate is *enforcing* (not just disclosing), the
> permission model is per-capability, and we can actually **measure** whether
> the beta is working (activation / retention / K-factor) — without violating
> the local-data moat.

## Trust: finish the safe-generativity gate

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 2.1 | Per-capability permission model (replace the single global boolean) | high | L | us-code | One approval grants **everything destructive**: `permission_enforcer.py:60-62` unknown method → `return True`; `:10-17` `METHOD_PERMISSIONS` has no calendar/email/messenger/`execute:*` entries; both call sites (`backend.py:139-140`, `runtime.py:122`) miss the map, so once `user_approved` is set, `send_email`/`delete_event`/`send_message` all pass. Add a capability taxonomy (gate spec). |
| 2.2 | Persist + timestamp + make approval **revocable** | medium | M | us-code | `approval_timestamp` declared (`models.py:70`) but assigned **nowhere** (verified); unload (`main.py:1036-1039`) leaves approval set — no revoke surface. Add `agent_consents` SQLite table + revoke route. |
| 2.3 | Consent on the **UGC install path** (shared/catalog skills) | high | M | us-code | `installer.py:275-364` (`install_from_bundle`) does validate + AST + deploy with **no consent step**; `skill_executor.py:62-84` execute bypasses the enforcer entirely; mobile `deep_link_service.dart:74-81` POSTs straight to `/skills/install-bundle` showing only snackbars. A friend-installed agent must surface the same ConsentCard locally. **Anti-pivot:** consent fires on the **receiving** device, share sheet unchanged. |
| 2.4 | Populate SSRF domain whitelist for mail/message agents | medium | M | us-code | `agents/email/manifest.yaml:25-26` and `messenger-hub/manifest.yaml:18-19` declare bare `network` with **no domains**, so `runtime.py:79-82` skips `set_allowed_domains` (whitelist never populated). Add explicit domains per agent. |
| 2.5 | Dry-run **enforcing** (gate, not just preview) | high | L | us-code | Promote 1.8 from show→block. **Requires the retest gate** (this is the part that changes runtime behavior). |

> The AST safety gate (`safety_gate.py:194-205`) is documented as
> **non-adversarial** — it is *not* a consent substitute. Keep it, but it does
> not satisfy any item above.

## Measurement: the growth funnel (local-first, moat-preserving)

> **Constraint (binding):** the project rule keeps in-app telemetry **out**
> (memory `feedback_app_minimalism`, dropped 2026-04-25). The honest design is
> two-phase: **(a) closed beta** = Vasily inspects testers' local DB / a
> one-line export, *no app surface*; **(b) at scale** = a single opt-in,
> no-PII, shown-before-send daily *counter* (counts only, never content).

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 2.6 | **Write the measurement-definitions doc first** | medium | S | us-design | Deck names the funnel (`docs/pitch/2026-06-19-investor-deck.md:170-176`) but never defines "install", the activation window, the retention denominator, or the K-factor formula. Define them under `docs/public-launch/` before any code. Operator-grade artifact the playbook asks for (`…demo-playbook.md:124-131`). |
| 2.7 | Activation metric — count users who created ≥1 agent by voice | medium | S | us-code | No event/funnel table: `database.py:12-49` has only conversations/agent_configs/dashboard_data/prefs/facts. Raw signal already lands locally (`conversations` ts+intent+agent `:13-21`; `agent_configs.installed_at :27`). One `created_via_voice` row on deploy (`flow.py` / `/builder/deploy` `main.py:1716`) satisfies it — **no SDK, no bloat**. |
| 2.8 | Retention signal — per-install daily rollup | high | M | us-code | No session/launch/last-seen table; no launch event persisted. `conversations.timestamp` approximates active-days (thin-but-not-absent). Add a per-install daily rollup. |
| 2.9 | K-factor attribution layer (additive) | high | M | us-code | **The loop already works** end-to-end (`deep_link_service.dart:57-95` → `/skills/install-bundle` `main.py:1961`). Missing is only attribution: the link `kali://import?n=…&d=…` (`deep_link_service.dart:59-61`) carries **no creator/agent id**, and there's no install counter. Add creator id to the link + a local tally. (Spec scopes this as Slice 4, post-demo: `…ugc-share-loop.md:97-99`.) |
| 2.10 | **Off-device aggregation sink** (cohort rollup) | high | M | **vasily** (decision) + us-code | The shared root cause behind the cohort halves of 2.7–2.9. No telemetry/export route exists (no `kernel/feedback.py`, no `/metrics`/`/telemetry`). Decision is Vasily's because it touches the moat: **(a)** beta = manual local-DB inspection / one-line export; **(b)** scale = single opt-in, no-PII, shown-before-send daily counters. |

**M2 engineering ≈ 3–4 weeks.** Trust items 2.1/2.5 are the heaviest and need
the retest gate before merging runtime behavior changes.

**Exit criteria:** agents can be granted *specific* capabilities, consent is
recorded and revocable, the UGC install path asks too, and Vasily can read a
real activation/retention/K number from the beta cohort.

---

# M3 — Public launch (open web download + Google Play)

> Goal: anyone can find a canonical download page, install the desktop app, get
> the Android app from Play, and a shared agent reaches a friend who *doesn't
> have the app yet*. This milestone is where **legal becomes a hard gate** —
> you cannot list on Play or distribute publicly without it.

## M3 blockers — hard prerequisites

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 3.1 | **Privacy Policy + EULA/ToS** (hosted, bilingual) | blocker | M | **legal** (+ us-design draft) | Repo-wide grep for privacy/eula/terms/оферта/политика → **0 files** (verified); no top-level LICENSE/NOTICE; `installer_premium.iss` has no `LicenseFile`. Required for public + Play. **Draft already exists** to hand to counsel: `docs/public-launch/play-store/privacy-policy.md` (local-data-first, honest about the LAN cleartext channel). |
| 3.2 | **Resolve FFmpeg GPLv3 copyleft conflict** | blocker | M | **vasily + legal** + us-code | 7 DLLs ship inside the *proprietary* installer with GPLv3 + libx264/libx265 (auditor verified `--enable-gpl`/`--enable-version3`/`libx264`/`libx265` + "libavutil license: GPL version 3 or later" in `models/ffmpeg/avutil-60.dll`; 7 DLLs present in `dist_premium/premium_stage/models/ffmpeg/`, no LICENSE alongside; pulled via `installer_premium.iss:62`). GPLv3 ⊗ proprietary redistribution. **Fix paths:** swap to LGPL/BSD FFmpeg build (no `--enable-gpl`, drop x264/x265), OR isolate FFmpeg as a separately-distributed component, OR remove if unused. Vasily picks; code executes. |
| 3.3 | **Google Play account + listing + Data Safety** | blocker | M | **vasily** (account) + us-code (assets) | No store presence. Needs a Play account, the **real upload key** (from 1.7), a hosted privacy policy (3.1), Data Safety for `RECORD_AUDIO`, content rating, review. **Submission pack already drafted:** `docs/public-launch/play-store/{store-listing,permissions,privacy-policy}.md`. |
| 3.4 | **Register + provision the landing/App-Links domain** | blocker | M | **infra + vasily** | `kali.app` is a **parked domain not owned** (302 → fortune.domains); only `kali://` is registered (no `assetlinks.json`, no `autoVerify`). `share_config.dart:14` `linkBase='https://kali.app'` is a placeholder; the https helpers are **dead code** (only `defaultHashtags` is used). Buy a domain, set `ShareConfig.linkBase`, host the landing + `/.well-known/assetlinks.json`. |

## M3 distribution & landing build-out

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 3.5 | Ship the landing page at the owned domain | medium | S | us-code + infra | **Already drafted** (self-contained, bilingual, dark theme): `docs/public-launch/index.html`. Fill `{{DESKTOP_DOWNLOAD_URL}}` / `{{ANDROID_APK_URL}}` and host on Cloudflare Pages. |
| 3.6 | Deferred install for an app-less friend (https landing + deep-link fallback) | high | L | us-code | The friend-without-app path is dead code: `kali://` share (`share_to_reels_screen.dart:64-68`) terminates at a backend they lack. Add `GET /a/:slug` to the landing (open `kali://` if installed, else store/desktop links). **Anti-pivot:** native share sheet + `kali://`, no OAuth. Spec defers this as Problem B / Slice 2. |
| 3.7 | App-Links host config (`assetlinks.json` + `autoVerify`) | medium | M | infra + us-code | `AndroidManifest.xml:35-40` registers only the custom `kali://` scheme. Add an https intent-filter with `autoVerify` + host `assetlinks.json` (depends on 3.4). |
| 3.8 | **Stand up the `kali-skills` catalog repo** (Сообщество source) | high | S | **vasily** + us-code | The verified catalog source 404s (WebFetch + `gh api` both 404). `catalog.py:130-134` trusts it as `verified`; degrades gracefully (`:391-394`) but returns **zero** community skills. Create the repo + seed it. |
| 3.9 | Desktop rebuild including `/skills/install-bundle` + `/skills/:name/export` | blocker* | M | us-code | Both routes **404 on the frozen backend** (uncommitted: `kernel/main.py` + `kernel/skills/installer.py` show as `M`; `install_from_bundle` impl `installer.py:275`). The mobile callers already exist. *Blocker **for the UGC loop**, not for a bare install — must land before share-to-friend works publicly. |
| 3.10 | Publish real store URLs (replace placeholders) | high | S | us-code (after 3.3) | `share_config.dart:16-19` store URLs marked "placeholders until published". Swap once the Play listing is live. |

## M3 product gates (UX honesty for mass-market)

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 3.11 | System-requirements gate is honest + cloud-voice fallback is surfaced | medium | S | us-design | `README.txt:13-19`: ~9GB on disk, ~12GB free, **NVIDIA RTX 20-series+** for local voice. ElevenLabs cloud fallback already exists (`:18,:32`) — make it a first-class "no GPU? use cloud voice" path in onboarding so the GPU requirement doesn't silently gate the mass market. |
| 3.12 | QR/link size fallback for large bundles | medium | S | us-code | Inline bundle link (`share_to_reels_screen.dart:64-68`) exceeds the QR cap (`_qrMaxChars=1800 :36`); full link still pasted in caption. With the landing host (3.4) switch to a short `<linkBase>/a/<slug>` link, bundle fetched server-side. |

**M3 engineering ≈ 4–6 weeks**, but **gated by 3.1/3.2/3.3/3.4 — all
human/legal/infra**. The code is mostly drafted; the blockers are *decisions
and provisioning*.

**Exit criteria:** a canonical https download page exists, the Android app is
on Play, a privacy policy + EULA are hosted, the FFmpeg license conflict is
resolved, and a shared agent reaches a friend who didn't have the app.

---

# M4 — Commercial / monetization (post-launch)

> Goal: turn on paid tiers. This is where the **remaining licensing and IP
> blockers** bite — they are fine for a free beta but **block the paid
> product** and any App Store / Play monetization.

| # | Item | Sev | Effort | Owner | Evidence |
|---|------|-----|--------|-------|----------|
| 4.1 | **Settle F5-TTS Russian license (CC-BY-NC-4.0)** | high | L | **vasily + legal** | NonCommercial clause blocks use in a **paid** product. Repo `Misha24-10/F5-TTS_RUSSIAN` (`tts_engine_f5.py:126,129-131`); model + ref **shipped** (`dist_premium/premium_stage/models/f5_russian_accent_tune.safetensors` + `jarvis_ref_v2.wav`). License per `…omnivoice-eval-spike.md:21`; already flagged to investors (`…investor-demo-playbook.md:88-89`). Commercial intent: `VISION.md:46` Pro $9.99/mo, `:51` $399 device. **Options:** commercial-license the checkpoint, retrain/replace (OmniVoice eval spike exists), or make Pro voice = ElevenLabs cloud only. |
| 4.2 | **Resolve JARVIS / Iron Man / Marvel IP exposure** | high | L | **vasily + legal** | Wake word `config/kali.yaml:7` `jarvis`; persona is JARVIS throughout `VISION.md`; **runtime admission of source**: `tts_engine_elevenlabs.py:197-198` sends `name:"JARVIS_KALI"`, `description:"JARVIS from Iron Man — Tony Stark's AI butler"` to ElevenLabs `/v1/voices/add` (also likely breaches their cloning ToS); **film-derived reference ships**: `jarvis_ref_v2.wav` ("9.62s, 4 clips from Sound Pack" = Iron Man dialogue, `tts_engine_f5.py:5`). Risk on record (memory `project_brand_naming`: store rejection, DMCA on reels, C&D, VC diligence flag). **Fix:** rename wake word/persona, replace the reference voice, scrub the EELabs metadata. Recall KALI=platform / Jarvis=persona split. |
| 4.3 | **THIRD-PARTY-NOTICES** + About→Licenses screen | medium | M | us-code | No aggregated notices ship (`installer_premium.iss:59-64` copies `premium_stage/*` with no NOTICE; `build_backend_premium.py:125-151` bundles openwakeword/f5_tts/vocos/ruaccent/faster_whisper/transformers/torch with no combined NOTICE). 9 OWW `.onnx` + torch/transformers ship with no LICENSE in repo/stage root. No About→Licenses surface (Flutter `showLicensePage` not wired). Required for clean commercial distribution. |
| 4.4 | Auto-updater (make the inert plugin real) | high | L | us-code | Declared-but-inert: `tauri.conf.json:53-58` points at unprovisioned `api.kali-os.com` with pubkey = base64("test_pubkey_placeholder"); plugin **absent** from `Cargo.toml`/`Cargo.lock`; only `tauri_plugin_shell` + `tauri_plugin_global_shortcut` registered (`lib.rs:216-217`); bundle target is InnoSetup, not a Tauri bundle the updater could service. Without it every release = re-shipping ~4.94GB by hand. (Audit BLD-5.) Pairs with the CDN host (1.5). |
| 4.5 | **iOS app** (only if iOS is in scope) | medium | L | us-code + vasily | Two hard blockers: bundle id still `com.example.kaliMobile` (`project.pbxproj:385,401,418`) and **no** `NSMicrophoneUsageDescription` (auto-reject + first-mic crash) while mic IS captured (`audio_recorder_service.dart:25-31`). Plus zero deep-link config (no `CFBundleURLTypes`/AASA). Signing is otherwise wired (`CODE_SIGN_STYLE=Automatic`). Needs an Apple Developer account (vasily). The standalone mobile design (below) sequences this. |
| 4.6 | Android brand hygiene | low | S | us-code | `AndroidManifest.xml:5` label `kali_mobile` (internal name) + namespace `com.example.kali_mobile`. Does **not** block submission (Play keys on `applicationId=ai.kali.mobile`, `build.gradle.kts:22`) — the deferral is a deliberate commented decision (`:8-10`). Tidy for launch polish. |

**M4 is gated by vasily/legal decisions (4.1/4.2), not engineering.** Until F5
and JARVIS are resolved, the **free** beta can ship but the **paid** product
and the JARVIS-branded cloud voice cannot.

---

# Cross-cutting: the standalone-mobile track

> The mobile app today is a **thin LAN client** — every screen calls a desktop
> backend at `http://<ip>:3006` (`chat_screen.dart:77`, `websocket_client.dart:34`,
> `agent_store_screen.dart:132`, `dashboard_screen.dart:27`); the user types the
> LAN IP by hand (`connection_screen.dart:106`). A friend with **no desktop**
> can receive a shared agent but **install nothing**. This is the mobile
> equivalent of the distribution blocker and threads through M1→M4.

**Recommended path (from the design spec): Option C — on-device lite engine
(default) + a thin opt-in cloud relay.** The backend splits cleanly:
orchestration is *not* GPU-bound (LLM router already cloud-capable
`llm_router.py:61-90`; skills run in-process `skill_executor.py:18-24`; TTS
already degrades no-GPU→ElevenLabs `tts_router.py:41-47`). So "standalone" =
re-host light orchestration + use the already-cloud voice path, **not** an ML
port to the phone. Reject a full cloud backend as the default (kills the moat +
recurring burn before PMF).

| Phase | Lands in | Effort | Owner |
|-------|----------|--------|-------|
| Identity/legal hygiene (iOS bundle id, mic desc, privacy policy) | M3/M4 | M | us-code + legal |
| On-device lite engine (cloud LLM/TTS, no heavy ML) | M3–M4 | XL | us-code |
| Landing + deferred deep link (app-less friend) | M3 (= 3.6) | L | us-code + infra |
| Cloud catalog (Сообщество) | M3 (= 3.8) | M | us-code + vasily |
| Pro cloud voice | M4 (= 4.1/4.2 gated) | L | us-code (blocked on license/IP) |

Full analysis: `docs/public-launch/2026-06-19-mobile-standalone-design.md`.

---

# Human-only critical path

> **These cannot be coded around. They are the real long pole — start them
> first, in parallel with M0/M1 engineering.** Each blocks a milestone.

| Item | Owner | Blocks | Why only a human |
|------|-------|--------|------------------|
| Buy **EV code-signing certificate** | vasily + legal | **M1** | Requires a legal entity, identity vetting, purchase. EV = instant SmartScreen trust. |
| Register + provision a **domain** (landing + App Links) | infra + vasily | **M3** (+ share loop) | `kali.app` is parked & not owned; must be bought and DNS/host configured. |
| Stand up **download host / CDN** (Cloudflare R2/Pages) | infra | M1 (host) / M3 (public) | Account + bucket + DNS; replaces manual Drive links. |
| **Privacy Policy + EULA/ToS** (hosted) | legal (draft exists) | **M3** | Legal text; draft at `play-store/privacy-policy.md` ready for counsel. |
| **FFmpeg GPLv3** resolution | vasily + legal | **M3** | Copyleft ⊗ proprietary; pick LGPL swap / isolation / removal. |
| **Google Play account** + Data Safety | vasily | **M3** | Account creation, identity, content declarations. |
| **Apple Developer account** (if iOS) | vasily | M4 | Account; gates any iOS work. |
| **F5-TTS CC-BY-NC-4.0** license call | vasily + legal | **M4 (paid)** | NonCommercial clause; license/retrain/replace decision. |
| **JARVIS / Marvel IP** call | vasily + legal | **M4 (paid) + store** | Rename/replace persona, voice ref, EELabs metadata. |
| Create **`kali-skills` catalog repo** | vasily | M3 (Сообщество) | GitHub repo creation + seeding. |
| Generate **Android upload keystore** | vasily | M1 (APK) / M3 (Play) | Secret key custody. |
| Push the 45 unpushed commits | vasily | M0 | Repo write. |

**Reading:** the code in M1–M3 is largely drafted or scoped. **What gates the
public launch is almost entirely the human/legal/infra column above** —
which is exactly why mass-market is the **~40%** horizon while the demo is ~90%.

---

# What we can build vs. what we cannot (summary)

**We (us-code) can ship without waiting on anyone:** consent disclosure +
dry-run preview (1.3, 1.8), per-capability permissions + persisted/revocable
consent (2.1, 2.2), UGC-path consent (2.3), SSRF whitelists (2.4), all
measurement instrumentation (2.6–2.9), the deferred-install landing logic
(3.6), QR fallback (3.12), THIRD-PARTY-NOTICES + About screen (4.3), the
on-device mobile engine (mobile track), version/pipeline cleanup (M0). The
signing/CDN *plumbing* (1.2, 1.5, 1.6) we wire — but only after the human buys
the cert and provisions the host.

**Only a human/infra/legal can unblock:** the code-signing cert, the domain,
the CDN account, the privacy policy + EULA, the FFmpeg GPLv3 decision, the Play
+ Apple accounts, the F5 license call, the JARVIS/Marvel IP call, the
`kali-skills` repo, the upload keystore. **Every milestone's *blocker* rows are
dominated by this column.**

---

# Artifact index

| Artifact | Path | Covers |
|----------|------|--------|
| **This roadmap** | `docs/public-launch/ROADMAP.md` | Master sequenced plan (both products) |
| Landing page (RU/EN, dark, self-contained) | `docs/public-launch/index.html` | M3.5 / M3.6 host (also the future deep-link import host) |
| Distribution spec (desktop + mobile) | `docs/public-launch/2026-06-19-distribution-spec.md` | M1 signing/host, M1.6 installer shape, mobile/App-Links |
| Mobile standalone design | `docs/public-launch/2026-06-19-mobile-standalone-design.md` | The standalone-mobile track (Option C) |
| Consent & dry-run gate spec | `docs/public-launch/trust/2026-06-19-consent-dry-run-gate-spec.md` | M1.3, M1.8, M2.1–2.5 |
| Play privacy policy (RU/EN draft) | `docs/public-launch/play-store/privacy-policy.md` | M3.1 (legal), M3.3 |
| Play store listing | `docs/public-launch/play-store/store-listing.md` | M3.3 |
| Play permissions justification | `docs/public-launch/play-store/permissions.md` | M3.3 (Data Safety) |

*(Pending, not yet drafted: the measurement-definitions doc — M2.6 — to be
written under `docs/public-launch/` before instrumentation code.)*

---

# Honest caveats

- **~40% is the mass-market number, and it is a trust/legal/distribution gap,
  not a feature gap.** The app *works*; what's missing is the safety surface
  (consent + dry-run), the install funnel (signing + a real host + store), and
  the legal foundation (privacy/EULA, FFmpeg GPLv3, F5 NonCommercial, JARVIS
  IP). This roadmap is ordered to close exactly those.
- **The frozen demo build is untouched** by everything here. All work begins on
  a post-demo branch.
- **Anti-pivot preserved end-to-end:** UGC stays native share sheet + `kali://`;
  consent fires locally on the receiving device; on-device data is framed as the
  moat throughout. No per-platform OAuth appears anywhere in this plan.
- **Every blocker tag was re-verified against the current tree** (HEAD
  `5043831`) this session: signing absent (`grep scripts/*` = 0), updater inert
  (absent from `Cargo.toml`/`lib.rs`), version skew (`Cargo.toml` 0.1.0 vs
  `tauri.conf.json` 0.2.0-beta), consent docstring verbatim
  (`main.py:1013-1024`), `unknown-method→return True` (`permission_enforcer.py:60-62`),
  install-bundle route uncommitted (`kernel/main.py` + `installer.py` = `M`),
  JARVIS metadata send (`tts_engine_elevenlabs.py:197-198`), shipped film-ref +
  F5 model, iOS `com.example.kaliMobile` + missing mic desc, no privacy policy
  in source, parked `kali.app`.
- **Effort numbers are engineering days.** They are *not* the calendar — the
  human/infra/legal critical path runs longer and in parallel, and is the true
  determinant of the launch date.
