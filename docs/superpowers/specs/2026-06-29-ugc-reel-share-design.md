# KALI — UGC Reel Share (backend-rendered 9:16 voice video) — Design Spec

**Date:** 2026-06-29
**Status:** Design — pending spec review + Vasily approval → writing-plans
**Anchor:** Competitive-differentiation vs OpenHuman. UGC-loop polish thread (selected over KALI-Super-Context, which becomes a later cycle).

---

## 1. Why this, why now (grounded competitive rationale)

A grounded recon of OpenHuman (`tinyhumansai/OpenHuman`, ~33,758★ verified via GitHub API; Product Hunt top-post badges — **not** a substantiated GitHub "#1 trending"; full recon: workflow `wf_991efc94-e56`, 2026-06-29) established, with authenticated `gh` code-search evidence:

- **Super Context is real, shipped code** (`context_scout` sub-agent, full stack) — give them credit; KALI cannot claim it as a gap.
- **Voice-authored agent creation for non-tech: ABSENT** (`gh search 'agent builder OR createAgent'` = 0). Voice is I/O only.
- **UGC create→share→install loop: ABSENT** (hard zeros for `reel/tiktok/ugc/shareAgent/import_agent`). Their only viral mechanic is a referral-code-for-credit program gated behind a signed-in managed backend; their "marketplace" is agent-to-agent crypto commerce — neither is "create agent → share reel → friend installs."
- **Mobile: scaffold only**, no shipped app; heavy-local Tauri-mobile, not a consumer UGC surface.

**Conclusion:** the UGC loop is KALI's genuinely unoccupied moat. KALI already has the loop's *plumbing* (voice build → export bundle → `kali://import` deep-link → install → callable; share-card PNG; «Сообщество» tab). The missing **irresistibility** is the share artifact itself: today KALI shares a **static PNG card**. On TikTok/Reels a static image does not spread — a short **video of the agent in action, in its own voice**, is the hook. That voice-in-action artifact is exactly what OpenHuman structurally cannot reproduce (no creation-by-voice).

This spec turns the share artifact from a static card into a **templated 9:16 MP4 reel** that plays the agent's voice.

---

## 2. Goals / Non-goals

### Goals
- A created agent can be shared as a short (~10–15s) vertical 9:16 MP4 in which the agent **speaks an auto-generated intro line in its voice**, over an animated card (waveform + burned subtitles), ending on a "scan to install" frame carrying the existing self-contained import link/QR.
- Rendering reuses what already ships in the installer (F5/ElevenLabs TTS, LLM router, the libav* FFmpeg DLLs) — **no new heavyweight binary, no GPL escalation**.
- Honest, graceful degradation: any failure falls back to the existing PNG card, then to text+link. No fake success, no crash.
- The reel is generated on the **creator's** desktop-connected backend; the **friend renders nothing** (they watch the reel and tap install).

### Non-goals (YAGNI — explicitly out of scope)
- On-device (Flutter) video rendering. (Avoids the archived/GPL `ffmpeg_kit_flutter` trap; deferred with the standalone-mobile engine, master-plan WS-4.7.)
- Mascot / talking-head / lip-sync avatar.
- Per-agent custom voices (voice is the global Jarvis persona — `VoiceConfig.tts_voice`).
- Creator-editable reel script (auto-intro is fixed for v1).
- Deferred-deep-link "install→auto-import the exact agent" friend path (a separate UGC weak-link; tracked, not built here).
- Changes to the import link / caption / hashtag format (`ShareConfig` stays the single source of truth).

---

## 3. Architecture & components

### 3.1 New backend module — `kernel/reel/generator.py`
Pure, testable functions (each ≤50 lines; file ≤800):

```python
async def build_intro_line(name: str, description: str, router: LLMRouter) -> str:
    """One-shot LLM call → a single short RU intro sentence
    ("Привет, я {name}. Я умею {…}"). On any LLM failure, return a
    deterministic template line built from name+description (never raises)."""

def synthesize_voice_clip(text: str) -> tuple[np.ndarray, int]:
    """Delegate to kernel.voice.tts_router.generate_audio(text), then
    NORMALIZE: cast to float32 and downmix to mono. `generate_audio` only
    guarantees `np.ndarray` — dtype/channel layout is not contractually
    float32-mono across F5 vs ElevenLabs, so normalize here to give the
    waveform-envelope + audio-mux logic a stable input. Returns
    (float32 mono audio, sample_rate)."""

def compose_reel(
    audio: np.ndarray, sr: int, *, title: str, subtitle: str,
    intro_text: str, link: str, out_path: Path,
) -> Path:
    """Render a 9:16 MP4 to out_path using PyAV (`av`) over the bundled
    libav* libraries. Frames rasterized with Pillow:
      (a) title card (agent name + description),
      (b) waveform pulse driven by audio amplitude envelope, with the
          intro_text shown as burned captions,
      (c) closing 'Сканируй, чтобы установить' frame with a QR of `link`.
    Audio muxed as an AAC/PCM track; video encoded H.264 via libopenh264.
    Raises on encode failure (caller maps to honest error)."""

async def generate_reel(name: str, *, registry, router, out_dir: Path) -> Path:
    """Orchestrator: resolve agent metadata → intro line → voice clip →
    compose_reel. Returns the MP4 path."""
```

**Codec decision (resolves a flagged risk):** H.264 via **libopenh264** (Cisco; BSD-licensed wrapper, royalties covered by Cisco's binary distribution). This keeps the proprietary installer **LGPL-clean** and does **not** worsen the existing FFmpeg-GPL gate (no `libx264`/`--enable-gpl`). Container MP4, faststart for social playback. (Considered and rejected: `libx264` — GPL escalation; `mpeg4` part 2 — LGPL-clean but weaker social-player compatibility.)

### 3.2 Backend route — `kernel/main.py`
Mirror the existing `GET /skills/{name}/export` pattern (currently ~main.py:2442):

```python
@app.get("/skills/{name}/reel")
async def skills_reel(name: str):
    # 1. resolve agent dir/metadata: SkillsRegistry.get(name) →
    #    fallback plugin_registry.skill_dir_for(name)  (same as export)
    # 2. reuse export's lowercase-latin name validation gate
    # 3. build the canonical import link via the shared helper used by export
    # 4. generate_reel(...) → FileResponse(path, media_type="video/mp4")
    # 5. on ANY failure → JSON {"status":"error","name":name,"message":...}
    #    (honest-fail; HTTP 200 with error envelope, matching export semantics)
```

### 3.3 Mobile — `mobile/lib/presentation/share_to_reels_screen.dart`
- `_prepare()` already fetches the export bundle and builds the link. Add: after the link is ready, fetch `GET /skills/{name}/reel`; if it returns `video/mp4`, save it to a temp file and remember the path.
- `_share()` shares `files: [<mp4>]` when present; **fallback chain**: reel MP4 → existing rendered PNG card (`_renderCardPng`) → text + caption-embedded link. The link, caption, hashtags, and on-screen QR are unchanged.
- **Content-type branching (explicit):** the `/reel` success path is binary `video/mp4` (a `FileResponse`), while failure is a JSON error envelope. The mobile client MUST branch on the response `content-type` (binary vs JSON) — do not blindly parse JSON. A non-`video/mp4` (or error-status) response triggers the PNG fallback.
- New UI affordance is minimal: the existing share button now produces a video; show a short "Собираю рил…" progress state while `/reel` is in flight (reuse the existing `_loading`/`shareLoading` copy).

### 3.4 Dependencies & distribution impact
- Add Python deps: `av` (PyAV — binds the libav* family), `Pillow` (frame raster), and `qrcode` (server-side QR raster for the closing frame). The QR dep is a **hard add**: the backend has no existing server-side QR raster (mobile's `qr_flutter` is client-only and not reusable here).
- PyAV wheels bundle their own LGPL FFmpeg libraries; ensure the openh264 codec is available to the wheel (bundle the Cisco `openh264` DLL into `premium_stage` via the scripted staging step — `build_installer_premium.bat`, `robocopy /E` not `/MIR`).
- **Installer must be rebuilt** for the feature to run live (consistent with the existing stale-installer note). Bundle-size delta (~tens of MB for PyAV) to be measured during the build-verify pass.

---

## 4. Data flow

```
mobile: tap «Поделиться»
  → GET /skills/{name}/reel
      → resolve agent (name, description) + build import link (ShareConfig form)
      → build_intro_line  (LLM one-shot; template fallback)
      → synthesize_voice_clip  (tts_router: F5 local / ElevenLabs fallback)
      → compose_reel  (Pillow frames + PyAV/libopenh264 encode + audio mux)
      → FileResponse(video/mp4)
  → save MP4 to temp → OS share sheet (video + caption w/ kali://import link)
friend in TikTok/Reels
  → taps link → (app installed) deep-link import / (not installed) landing → store → install
  → imported agent is LLM-callable  (existing Phase A loop)
```

---

## 5. Error handling (honest degradation)

| Failure point | Behavior |
|---|---|
| Unknown / non-shareable agent name | Route returns `{status:"error", message}` (same gate as export); mobile shows export-failed copy. |
| LLM intro generation fails | `build_intro_line` returns deterministic template line; reel still renders. |
| TTS unavailable / raises | Route returns honest error; mobile falls back to PNG card. |
| PyAV/encode fails | Route returns honest error; mobile falls back to PNG card. |
| `/reel` times out / network | Mobile falls back to PNG card, then text+link. |

No code path emits a success status for a no-op. No 500 crash surfaces to the user.

---

## 6. Testing strategy

**Python e2e (`-m core_loop`, ML-free, runs in CI/seconds):**
- `tests/e2e/test_core_loop_reel_share.py`:
  - Mock LLM with the existing `_StubRouter` (returns the intro line); mock TTS via `monkeypatch` to return a tiny synthetic ndarray + sr (no torch/F5).
  - Run a **real PyAV encode** on the ~1s clip (PyAV wheels are self-contained, so CI needs no system FFmpeg).
  - Assert: HTTP 200; `content-type: video/mp4`; non-empty body; probe the output has exactly 1 video stream + 1 audio stream; duration within an expected range; the encoder used is the configured H.264 (libopenh264).
  - Honest-fail test: unknown agent → JSON error envelope, status 200, no exception.
  - Fallback test: TTS raises → route returns error envelope (mobile-side fallback covered in the Flutter test).
- Unit tests for `build_intro_line` template fallback (LLM raises → deterministic line) and `compose_reel` (produces a valid MP4 from a fixed tiny audio buffer).

**Flutter widget test:** `/reel` returns mp4 → share invoked with the video file; `/reel` errors → share falls back to the PNG card path. (Run on `kali_test_34` per the mobile-E2E memory; not the corrupting `Pixel_7` AVD.)

**Manual/live (deferred to the consolidated live-verify pass):** rebuild installer → create an agent by voice → share → confirm a real MP4 with audible Jarvis voice plays in a social app; the existing two-device import loop is unchanged.

---

## 7. Anti-pivot check ✓

- Inputs are **KALI-native only**: the agent's own name/description and the global Jarvis voice. Zero OAuth, zero third-party integrations, no life-aggregation. Does not drift toward OpenHuman's 118-integration / OS-assistant DNA.
- Reinforces the two un-copyable axes (voice-authored creation + UGC share loop), not their battlefield.
- Reuses the existing self-contained `kali://import` / https deep-link (no new distribution format); `ShareConfig` remains the single source of truth.

---

## 8. Risks & open items

- **Bundle size / build:** PyAV + openh264 add to the already-large installer; measure during build-verify. Mitigation: PyAV is needed only on the desktop (creator) side.
- **openh264 acquisition:** confirm the Cisco openh264 binary is resolvable by the PyAV wheel on the target Windows build; if not, the staging step fetches/stages it. (Legal note: openh264 royalties are covered by Cisco's distribution; document the bundled license text — consistent with the existing FFmpeg license-text task.)
- **Render latency:** a ~12s reel should encode in a few seconds on the creator's machine; show progress, set a mobile client timeout, and fall back on timeout.
- **Voice availability offline:** if neither F5 (GPU) nor ElevenLabs (key/network) is available, there is no voice clip → honest fallback to PNG. Acceptable for v1.

---

## 9. Out-of-scope follow-ups (noted, not built here)
- Deferred-deep-link friend path (install → auto-import the tapped agent) — the other UGC weak link.
- «Сообщество» engagement depth (remix, creator profiles, trending feed).
- SKILL.md "works everywhere" interop proof.
- KALI-Super-Context on local agents/voice-history (separate brainstorm cycle).
