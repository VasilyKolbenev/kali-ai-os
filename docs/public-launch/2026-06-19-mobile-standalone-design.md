# Mobile Standalone — Design Spec

**Status:** design (2026-06-19). Read-only artifact; no code changed.
**Author task:** resolve the "mobile-needs-desktop" blocker so a friend **without a
desktop** can create and run agents from the phone alone.
**Scope:** architecture decision + option comparison + recommendation. Design only.
**Anti-pivot anchors (binding):** UGC publishing uses the **OS native share sheet**,
never per-platform OAuth/API. **On-device / local-data** is the moat — every option
below is judged on whether it preserves that positioning.

---

## 1. The blocker, stated precisely (verified)

The Flutter app is a **thin LAN client to the desktop backend**. It has no local
intelligence of its own. Every meaningful screen makes an HTTP/WS call to a backend
the user must already be running on another machine on the same network:

| Mobile feature | Call it makes | File:line |
|---|---|---|
| Connect | user **types the desktop's LAN IP**; opens `ws://<ip>:3006/ws` | `mobile/lib/presentation/connection_screen.dart:21-22,40-43`, `mobile/lib/core/websocket_client.dart:34` |
| Chat | `POST http://<ip>:3006/chat` | `mobile/lib/presentation/chat_screen.dart:77` |
| Voice | streams over the same `:3006/ws`, plays back `voice.tts_chunk` | `mobile/lib/presentation/voice_screen.dart:40-52,78` |
| Agent list / toggle | `GET /agents`, `/agents/running`, `POST /agents/{n}/load\|unload` | `mobile/lib/presentation/agent_store_screen.dart:132-133,168` |
| Discover / install | `GET /skills/catalog`, `POST /skills/install` | `mobile/lib/presentation/agent_store_screen.dart:317,341` |
| Import shared agent | `POST /skills/install-bundle` | `mobile/lib/core/deep_link_service.dart:75` |
| Share an agent | `GET /skills/{n}/export` | `mobile/lib/presentation/share_to_reels_screen.dart:59` |
| Dashboard | `GET /dashboard` | `mobile/lib/presentation/dashboard_screen.dart:27` (`apiUrl` → `http://<ip>:3006`, `mobile/lib/core/http_client.dart:20`) |

`serverIpProvider` defaults to **null** (`mobile/lib/core/config.dart:3`); with no IP,
every screen shows "not connected" and the UGC import explicitly bails:
`deep_link_service.dart:66-70` ("`importConnectFirst`"). The connect screen even tells
a real-phone user to enter `192.168.x.x` by hand (`connection_screen.dart:106`).

**Consequence for the viral loop.** The P2P import path *is* built end-to-end
(`kali://import?n=&d=<bundle>` → `/skills/install-bundle`, handler at
`kernel/main.py:1961`), but it terminates at a backend the friend doesn't have. A
строитель who taps a friend's shared agent installs **nothing** unless they also own a
Windows + NVIDIA-GPU desktop running the ~9 GB install. That gates the entire
distribution model the product is bet on.

### What the backend actually requires — the load-bearing distinction

The desktop backend is **not** monolithically heavy. It splits cleanly:

- **Lightweight orchestration (no GPU, no big models):**
  - `/chat` routes through the **LLM router**, which already supports a cloud provider
    (Claude) and a local one (Ollama) and picks per request
    (`kernel/llm_router.py:61-90`). With a cloud key, chat needs no GPU.
  - **Skills run in-process as Python template classes** — tracker / reminder /
    monitor / notifier / logger (`kernel/skill_executor.py:18-24,62-84`). No ML.
  - The **builder** is intent-classify → wizard → generate files → deploy
    (`kernel/builder/flow.py:52-173`); its one model touch (single-shot extraction,
    `kernel/builder/extractor.py:1-12`) is **cloud-LLM-capable and already falls back**
    when the LLM is unavailable.
  - `/agents`, `/skills/*`, `/dashboard` are plain orchestration + SQLite
    (`kernel/database.py`).
- **Heavy local ML (the only GPU-bound part):**
  - **F5-TTS Russian** voice clone on CUDA (`kernel/voice/tts_engine_f5.py`), and
  - **faster-whisper** STT (`kernel/voice/stt.py:1,48-60`), plus torch.
  - The TTS router **already** degrades no-GPU → ElevenLabs cloud
    (`kernel/voice/tts_router.py:5-6,41-47`).

**This split is the whole design.** "Mobile standalone" does **not** require porting
F5/Whisper/torch to a phone. It requires hosting the *lightweight orchestration*
somewhere the phone can always reach, and sourcing voice from the path that is
**already** cloud-capable. Everything below builds on that fact.

---

## 2. Constraints & non-negotiables

1. **Native share only.** No TikTok/IG/YT OAuth. (Matches
   `docs/superpowers/specs/2026-06-19-ugc-share-loop.md:5,16-26`.)
2. **On-device/local-data is the moat — keep it true, and keep it true in marketing.**
   VISION.md:746 already frames the product as "Local-first, cloud-enhanced." Any
   option that silently ships personal data to a KALI-run server **without** an honest,
   visible boundary breaks the one differentiator we have. Privacy is a **strength to
   preserve**, not a gap to paper over.
3. **Non-tech target** (строитель/врач/таксист). "Type your LAN IP" and "run a 9 GB
   GPU app first" are both disqualifying for the standalone user. First-run must be
   tap-and-go.
4. **Frozen demo build is untouched.** This is post-demo product design; nothing here
   changes the artifact going to the investor in a few days.
5. **No new platform OAuth, no PII telemetry** (consistent with the project's
   minimalism rule, MEMORY `feedback_app_minimalism`). Author identity for the UGC loop
   may start anonymous (device id), per the share-loop spec line 38.

---

## 3. Options

Three ways to give the standalone phone a backend it can always reach. For each:
**capability, privacy, cost, effort, risk.** Effort is relative (S/M/L/XL) — design
estimate, not a commitment.

### Option A — Cloud backend (KALI-hosted multi-tenant)

Host the lightweight orchestration (`/chat`, `/agents`, `/skills/*`, `/dashboard`,
builder, in-process template skills) as a managed multi-tenant service. The phone talks
to `https://api.<placeholder-domain>` instead of `http://<lan-ip>:3006`. Voice uses
the cloud path (ElevenLabs today; a KALI GPU inference server later). LLM is cloud
(BYO key or KALI-metered).

- **Capability:** Full parity for the non-voice-ML surface, instantly, for any phone
  with internet. No desktop, no LAN, no GPU. Tap-to-install from a shared link works
  because the import endpoint now lives at a stable URL the friend can always reach.
  This is the **only** option that closes the viral loop for a true zero-device friend
  on day one.
- **Privacy:** **Weakest by default, and this is the core tension.** Personal data
  (chat, agent configs, the `user_facts` memory table — `kernel/database.py`) would
  transit and rest on KALI infrastructure. That directly contradicts the local-data
  moat *unless* it is reframed honestly: a per-tenant encrypted store, a written data
  policy, no training on user data, and an in-app boundary that says plainly what lives
  in the cloud. It is recoverable, but only with real legal+infra work
  (note: no privacy policy / EULA exists yet — repo-wide grep is clean), not a
  marketing sentence. Agents that touch real accounts (email/calendar) make this worse:
  the consent model is still a single global boolean
  (`kernel/sandbox/permission_enforcer.py:56-63`) with no dry-run, which is far more
  dangerous server-side than on a user's own LAN.
- **Cost:** **Highest, and recurring.** Per-active-user compute + storage + egress; an
  LLM bill if not strictly BYO-key; on-call/ops; abuse handling (the backend
  *generates and runs code* — `kernel/builder/flow.py`, `kernel/skill_executor.py` —
  so multi-tenant code execution needs hard sandboxing/isolation per tenant). This is a
  business model decision, not just an infra line item; it pairs with VISION.md:45-46
  Free/Pro tiers but turns "local & free" into "someone pays for every session."
- **Effort:** **XL.** New service, auth/identity, multi-tenant data isolation,
  per-tenant secret storage for LLM keys, sandbox hardening for hostile generated code,
  the privacy/legal layer, and the domain/cert/CDN that don't exist yet (the updater
  endpoint `api.kali-os.com` is an unprovisioned placeholder, `tauri.conf.json:55`;
  `kali.app` is not owned — 302s to a parking page).
- **Risk:** Highest blast radius (one breach = everyone's data + everyone's API keys);
  ongoing burn before PMF; it is the **anti-pivot of the privacy story** if shipped
  carelessly; and it concentrates the very "run arbitrary generated code" surface the
  audit already flagged into a single internet-facing target.

### Option B — Lite local backend on-device (no heavy ML; cloud LLM/TTS)

Embed the **lightweight orchestration** *inside the Flutter app* so the phone is its
own backend. No `:3006` over LAN, no desktop. The on-device engine handles: chat
orchestration, the **template skill runtime** (the five templates are plain logic),
agent enable/disable, the builder wizard, dashboard assembly, local SQLite, and
**install-from-bundle** (the P2P import target moves on-device). The two genuinely heavy
pieces are **delegated to the cloud over the user's own credentials**: LLM via the
existing router's cloud path, **TTS/STT via ElevenLabs/cloud** (the no-GPU branch the
router already takes, `tts_router.py:41-47`). No F5/Whisper/torch on the phone.

- **Capability:** Standalone create-and-run for the **template-skill** product:
  voice/text chat (cloud LLM), build-an-agent-by-voice (cloud STT + cloud LLM extract +
  local template generate/deploy), run agents, dashboard, and — critically —
  **receive a shared agent with no server** (the bundle is self-contained in the link;
  importing it becomes a local operation). The viral loop closes **P2P, device-to-
  device**, which is the most on-brand possible shape: a friend's agent installs into
  *their* phone, not into a KALI server. Honest limits: agents needing a 24/7
  always-on trigger (cron) only fire while the app/OS lets it run; truly heavy custom
  Python agents (vs the five templates) are out of scope on a phone; the F5 "our voice"
  is not available on-device (cloud voice instead).
- **Privacy:** **Strongest — it literally *is* the moat.** Personal data, agent
  configs, and memory stay in the phone's own sandbox; nothing transits a KALI server.
  The only things that leave the device are (a) the LLM prompt to the user's chosen
  provider and (b) TTS/STT audio/text to the voice provider — both under the user's own
  key, both honestly disclosable as "your assistant talks to the AI model you chose."
  This preserves "data never leaves your device (except the model call you control)"
  as a **true** statement, which is exactly what the positioning needs.
- **Cost:** **Lowest for KALI — no servers to run.** Per-user inference cost is the
  user's (BYO key) or a thin metered Pro tier; there is no KALI compute/storage/egress
  baseline. This keeps the Free tier (VISION.md:45) genuinely free-to-host.
- **Effort:** **L–XL, front-loaded once.** The hard part is a **second
  implementation** of the orchestration in Dart (or embedding a Python runtime in the
  app). The Python orchestration is modest and mostly non-ML, but it is real work to
  re-express the LLM-router client, the five skill templates, the builder
  wizard/extract/deploy, bundle import, and the dashboard assembly — plus the local
  scheduler caveats. Parity-drift risk between the desktop kernel and the mobile engine
  is the standing maintenance tax.
- **Risk:** Two codebases for the same logic (drift); mobile-OS background-execution
  limits make "always-on" agents weaker than on desktop (must be set honestly in copy);
  app size grows if a Python runtime is embedded. None of these threaten the privacy
  story — they are scope/honesty risks, not trust risks.

### Option C — Hybrid (on-device lite engine **+** optional KALI cloud relay)

Ship Option B as the **default and the privacy guarantee**, and add a **thin, optional,
opt-in cloud relay** for the things on-device genuinely can't do: a stable HTTPS host
for **deferred deep links** (friend taps a link before installing the app → store →
deferred import) and the **catalog/"Сообщество"** discovery surface, plus an optional
**premium voice relay** to a KALI GPU server for "our JARVIS voice" without requiring
the user's own ElevenLabs key. The relay carries **bundles and discovery metadata**,
not the user's personal data; personal data and agent execution stay on-device by
default. A user who never opts into anything still has a fully standalone, fully local
product.

- **Capability:** Everything Option B does, **plus** the two things B can't: a real
  landing/deferred-install path for friends who don't have the app yet (Problem B in
  the share-loop spec, lines 28-38, 86-91, currently dead code in
  `share_config.dart:14,32`), and a discoverable cloud catalog beyond P2P. Optional
  premium cloud voice closes the "I want the branded voice but have no GPU and no
  ElevenLabs key" gap, mapping cleanly to Pro (VISION.md:46).
- **Privacy:** **Strong and, crucially, *honest by construction*.** The default is
  on-device (moat intact). The relay's job is deliberately narrow — move **agent
  bundles** (already shareable artifacts) and **catalog metadata**, and *optionally*
  proxy voice — so the privacy boundary is a clean, explainable line: "your data stays
  on your phone; only the agent you choose to share, or the link a friend taps, goes
  through us." Opt-in premium voice is a per-feature, user-initiated exception, not a
  silent default. This is the only option that **lets you keep the moat *and* close the
  zero-device-friend funnel**.
- **Cost:** **Low-to-moderate, and scoped.** The relay is far cheaper than Option A
  because it doesn't run per-user orchestration or hold personal data — it serves
  static-ish bundle/catalog content (a CDN + small API) and *optionally* a voice GPU
  pool sized to paying Pro users only. No multi-tenant code-execution cost.
- **Effort:** **XL overall** (it is B **plus** the relay/landing/catalog automation and,
  if pursued, the voice GPU service) — but **phaseable**: B alone is shippable and
  useful before any relay exists; the relay lands incrementally (landing+deferred link
  first, catalog automation next, premium voice last).
- **Risk:** More moving parts than B; the relay still needs the domain/cert/landing
  that don't exist yet (placeholders below); premium-voice GPU ops is real but bounded
  to Pro. The key risk to manage is **keeping the relay narrow** — if it ever creeps
  into "just store the user's data too," it collapses into Option A and loses the moat.

---

## 4. Comparison at a glance

| Dimension | A — Cloud backend | B — On-device lite | C — Hybrid (B + thin relay) |
|---|---|---|---|
| Zero-device friend can create+run | Yes (day 1) | **Yes** (P2P) | **Yes** (P2P + deferred-link install) |
| Closes deferred-link funnel (no app yet) | Yes | No (needs app first / direct bundle) | **Yes** |
| Cloud catalog / "Сообщество" discovery | Yes | P2P only | **Yes (optional)** |
| "Our" F5/JARVIS voice without user GPU/key | Possible | No (cloud voice w/ user key) | **Optional (Pro relay)** |
| Always-on (cron) agents | Strong (server) | Weak (OS background limits) | Weak by default / strong if relay-scheduled (future) |
| **Privacy / local-data moat** | **Weakest** (data on KALI infra) | **Strongest** (data on-device) | **Strong + honest boundary** |
| **KALI cost** | **Highest, recurring** | **Lowest** (no servers) | **Low–moderate** (bounded relay) |
| **Effort** | XL | L–XL | XL (phaseable; B ships first) |
| **Risk** | Breach blast radius; burn; anti-privacy | Code-duplication / drift; background limits | More parts; relay scope-creep |
| Anti-pivot aligned (native share) | Yes | Yes | Yes |

---

## 5. Recommendation

**Adopt Option C, sequenced — but ship Option B first and treat it as the product's
spine.**

Rationale:

1. **B is the only option that *strengthens* the one moat we have.** The whole pitch is
   non-tech voice creation + on-device/local-data trust (MEMORY `project_vision`,
   `project_ugc_interop_pitch`). An on-device lite engine makes "your data never leaves
   your phone" **literally true** while delivering full standalone create-and-run for
   the template-skill product. Option A trades the moat for convenience and turns a
   free local product into a per-session server bill — the wrong trade before PMF.

2. **The architecture already wants this.** The backend's heavy ML is cleanly isolable
   from its orchestration; the LLM router and TTS router *already* have cloud paths for
   the no-GPU case (`kernel/llm_router.py:61-90`, `kernel/voice/tts_router.py:41-47`);
   skills are in-process Python logic, not models (`kernel/skill_executor.py:18-24`).
   "Standalone" is therefore a **re-host of light orchestration**, not an ML port.

3. **The P2P loop is the most on-brand viral mechanic available** and is *almost* there:
   `kali://import` + self-contained bundle + `/skills/install-bundle` already exist
   (`deep_link_service.dart`, `kernel/main.py:1961`). Moving the import target on-device
   makes a friend's agent install into **their phone**, server-free — the purest
   expression of the local-data story.

4. **The thin relay (C) earns its keep only where on-device genuinely can't reach:**
   the **deferred-install landing** for friends who don't have the app yet (today dead
   code + an unowned domain), the **cloud catalog** for discovery beyond P2P, and an
   **opt-in premium voice** for Pro. Each is additive, narrowly scoped to **bundles +
   metadata (+ optional voice)**, and never holds the user's personal data — so the moat
   survives. Keeping the relay narrow is the explicit design guardrail; the moment it
   stores user data it becomes Option A.

**What this is *not*:** it is not a mandate to host everyone's chat history and API keys
in our cloud (Option A). If a managed backend is ever wanted for an enterprise/Team SKU
(VISION.md:47 "on-prem option"), treat it as a separate, opt-in, paid deployment — not
the default path for the строитель installing from a friend's reel.

### Suggested sequencing (design intent, not a commitment)

- **Phase 0 — Honesty + identity hygiene (prereq, cheap).** Fix the mobile identity
  blockers that gate *any* public mobile launch, independent of A/B/C: iOS bundle id is
  still `com.example.kaliMobile` with **no `NSMicrophoneUsageDescription`** (auto-reject
  + first-mic crash, `mobile/ios/Runner.xcodeproj/project.pbxproj:385`, mic used at
  `mobile/lib/core/audio_recorder_service.dart:25-31`); store URLs are placeholders
  (`share_config.dart:16-19`). And write the privacy/EULA the cloud-touching paths
  legally require (none exists today).
- **Phase 1 — Option B (the spine).** On-device lite engine: chat (cloud LLM), build-by-
  voice (cloud STT + cloud LLM extract + local generate/deploy), run template agents,
  dashboard, local SQLite, **bundle import on-device**. Standalone, fully local,
  server-free. Honestly label background/always-on limits.
- **Phase 2 — Relay part 1: landing + deferred deep link.** Stand up the
  `linkBase`/App Links host (placeholder below) so a friend **without the app** can tap
  a shared link → store → deferred import. This is the funnel B can't cover.
- **Phase 3 — Relay part 2: cloud catalog ("Сообщество") + optional attribution.**
  Discovery beyond P2P; anonymous device-id author identity per share-loop spec line 38.
- **Phase 4 — Relay part 3 (Pro): premium cloud voice.** KALI GPU inference for "our
  JARVIS voice" without the user's own key. Gated to Pro (VISION.md:46). **Blocked on
  the licensing items below — do not ship branded/F5 voice commercially until resolved.**

---

## 6. Hard dependencies & honest caveats (must resolve before the relay is real)

These are not solved by this design and several are launch-blockers flagged elsewhere;
listing them so the recommendation isn't read as "free."

- **Domain / landing / certs are unprovisioned.** `linkBase = https://kali.app`
  (`share_config.dart:14`) is a placeholder; `kali.app` is **not owned** (302 → parking
  page) and serves no `/.well-known/assetlinks.json`. The updater endpoint
  `api.kali-os.com` (`tauri.conf.json:55`) is also a placeholder. **No relay/landing is
  real until a domain is chosen, owned, and configured as the App Links / Universal
  Links host.** → see placeholders below.
- **The https deep-link path in the app is currently dead code.** `agentLink()` /
  `linkBase` are defined but unused — only `defaultHashtags` is referenced
  (verified: grep of `mobile/lib` shows `agentLink`/`linkBase` only in
  `share_config.dart`). The live path is `kali://import` with the inline bundle. Phase 2
  is what activates the https path.
- **Voice licensing blocks commercial branded voice (Phase 4).** F5 Russian model is
  **CC-BY-NC-4.0** (NonCommercial) and the shipped reference `jarvis_ref_v2.wav` is
  film-derived ("JARVIS from Iron Man", sent to ElevenLabs at
  `kernel/voice/tts_engine_elevenlabs.py:196-199`). Marvel/Disney IP + NC license are
  on record as launch risks (MEMORY `project_brand_naming`, `feedback_tts_stack`). A
  cloud premium-voice relay **inherits** these — resolve license/persona before any
  paid voice ships.
- **Consent model is not standalone-ready.** Permissions are a single global boolean
  with no dry-run (`kernel/sandbox/permission_enforcer.py:56-63`,
  `kernel/builder/flow.py:135-173`). On a standalone phone this is *better* than on a
  server (data is local), but agents touching real accounts still need the plain-language
  consent + dry-run gate (separate design debt; out of scope here, but a prerequisite
  before "run my agent against my email" on any standalone build).
- **Always-on agents degrade on mobile.** Desktop cron (`kernel/builder/deployer.py`)
  has no faithful phone equivalent; OS background limits mean scheduled agents fire only
  when allowed. Either set this honestly in copy (Phase 1) or move scheduling to the
  relay later (a deliberate, opt-in cloud feature, not a silent default).
- **No off-device aggregation / metrics sink exists** (verified: no `/telemetry`,
  `/metrics`, `kernel/feedback.py`). Not required for standalone to function; relevant
  only if the relay later needs K-factor attribution (keep it opt-in, no-PII, counts-not-
  content, per the project's minimalism rule).

### Placeholders (do not invent — choose and replace)

- `<LANDING_DOMAIN>` — the App Links / Universal Links host (candidate `kali.app` is
  **not yet owned**). Replaces `share_config.dart:14` `linkBase`.
- `<API_DOMAIN>` — relay base for catalog/bundle/voice (candidate `api.kali-os.com` is
  a placeholder). 
- `<ANDROID_STORE_URL>` / `<IOS_STORE_URL>` — real store listings once published
  (`share_config.dart:16-19` are placeholders; apps not yet published).
- `<CATALOG_REPO>` — the `kali-skills` catalog repo (per share-loop spec line 105;
  not yet created/confirmed).
- `<TLS_CERT>` — certificate for the chosen domain (none provisioned).

---

## 7. One-paragraph answer (for a reviewer in a hurry)

A friend with no desktop today installs **nothing** when they tap a shared agent,
because the whole mobile app is a thin client to a desktop backend on `:3006` they don't
have. The fix is **not** to port heavy ML to the phone — chat, skills, and the builder
are lightweight, cloud-LLM-capable orchestration that's cleanly separable from the
GPU-bound F5/Whisper voice (which already has a cloud fallback). Recommendation:
ship an **on-device lite backend** (Option B) as the spine — it makes "your data stays
on your phone" literally true and closes the viral loop **P2P, server-free** — then add
a **deliberately thin, opt-in cloud relay** (Option C) only for what on-device can't do
(deferred-link landing for app-less friends, cloud catalog, optional Pro voice), keeping
the relay scoped to bundles + metadata so the local-data moat stays intact. Reject a
full multi-tenant **cloud backend** (Option A) as the default: it is the most expensive,
the highest breach risk, and the direct opposite of the privacy positioning the product
is sold on.
