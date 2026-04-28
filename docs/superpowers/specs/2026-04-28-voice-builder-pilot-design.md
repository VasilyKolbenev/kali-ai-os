# voice-builder-pilot — Design Spec (v2)

> Status: design draft, v2 (post spec-review). Created 2026-04-28. Sub-project of Tier 2 #10 (Agent Store v2). Builds **on top of** the existing text-based pilot shipped under plan `docs/superpowers/plans/2026-04-22-voice-builder-pilot.md`.

**One-line summary:** voice-first enhancement layer over the existing `BuilderPanel` text pilot — new L1 layout (mic-first stage), browser audio capture, push-to-talk + frontend VAD, single-shot extraction (A4), TTS readback for wizard questions and final preview (A6), template-anchored phrasing (A7), and an always-on visual transcript + spec-card track (A2). No second pilot — this replaces the current `BuilderPanel` UI surface and extends the existing Zustand store / API client.

---

## Goal

Make voice-first agent creation real: the user taps a microphone, speaks what they want ("трекер воды каждые 2 часа"), and within seconds either (a) sees a deployed skill or (b) goes through a short voice-driven wizard that never feels like "filling out a form by talking."

**Why this is a separate sub-project (vs folded into Agent Store v2):** Tier 2 #10 leads with a hero CTA "🎤 Скажи что нужно — сделаем агента." That CTA needs a target screen. Building the target as its own sub-project keeps each spec focused, lets us dogfood the voice flow before integrating it into the marketplace, and makes Store v2 a clean wrap around an already-working creator surface.

## Vision alignment

Public-launch quality bar — voice-first creation for non-tech users is the differentiator vs OpenClaw. The pilot is the moment that promise meets reality. UGC distribution depends on the surface being demoable in a 15-second reel; A4 fast-path is what compresses a multi-step wizard into a one-tap demo.

---

## Existing baseline (what's already shipped)

The 2026-04-22 plan landed a working **text-based** builder pilot. Files in tree today:

**Backend (Python, all working):**
- `kernel/builder/session_store.py` — `SessionStore`, `BuilderSession`, TTL eviction (1800s default).
- `kernel/builder/flow.py` — `BuilderFlow` orchestrator: `start`, `answer`, `deploy`, `cancel`, `_build_spec` (Russian-substring-keyed config mapping).
- `kernel/builder/wizard.py` — `create_wizard`, `_skill_questions(template)` returning fixed question lists per template.
- `kernel/builder/intent_classifier.py` — `classify_intent` (LLM-preferred + regex fallback), `_LLM_SYSTEM_PROMPT` already spelled out — model for `/builder/extract` prompt below.
- `kernel/builder/skill_generator.py`, `kernel/builder/deployer.py` — generate + install on disk.
- `kernel/main.py` — endpoints `POST /builder/{classify,start,answer,deploy,cancel,create-skill,create-agent}`.
- `kernel/main.py` — endpoints `POST /tts`, `POST /tts/speak`, `POST /synthesize`, `GET /health/tts`.
- `kernel/workers/tts_worker.py` — bridge worker handles `stt_transcribe` op (audio_b64 = base64 **i16 LE PCM**, plus `sample_rate` field, server resamples to 16 kHz via `scipy.signal.resample_poly`). Driven by the **Rust backend** (`src-tauri/src/backend/voice/bridge.rs`), not by the Python kernel. The Python `kernel/voice/pipeline.py` uses `SpeechToText` directly in-process and never crosses a subprocess boundary. We do not depend on the Rust bridge — instead we replicate the i16/resample logic in a thin HTTP handler that calls `SpeechToText` directly. Reference for the audio-framing + resample code: `tts_worker.py` lines 143-199.

**Frontend (React, all working):**
- `ui/src/api/builder.ts` — typed client: `builderApi.{start,answer,deploy,cancel}`.
- `ui/src/stores/builder.ts` — Zustand `useBuilderStore` with phases `idle | asking | generating | previewing | deploying | done | error`.
- `ui/src/components/Builder/BuilderPanel.tsx` — root component (text input + Enter to submit + manual answer flow).
- `ui/src/components/Builder/BuilderProgress.tsx` — phase label + step dots.
- `ui/src/components/Builder/BuilderPreview.tsx` — preview card + Запустить/Отменить buttons.
- `ui/src/components/Builder/StarterExamples.tsx` — 5 prefilled prompts.
- `ui/src/App.tsx` — mounts `<BuilderPanel />` at `mode === "builder"` (Zustand mode switch, **NOT react-router**).
- Mode switching is via `useAppStore.setState({ mode: "builder" })` from `Sidebar` or any caller.

**Routing convention:** the codebase has no `react-router-dom`. All "routes" are mode strings. Tier 2 #10's Hero CTA wires up by calling `useAppStore.setState({ mode: "builder" })`, not `navigate("/builder")`.

## What this spec changes vs the existing pilot

| Surface | Today | After this spec |
|---------|-------|-----------------|
| `mode === "builder"` mounts | `BuilderPanel.tsx` (text only) | `VoiceBuilderScreen.tsx` (voice-first, L1 layout) |
| `useBuilderStore` phases | `idle / asking / generating / previewing / deploying / done / error` | extended with `listening / transcribing / extracting`; existing phases keep the same names |
| `BuilderProgress.tsx` | dots + phase label | merged into the L1 spec card (deleted as a standalone component) |
| `BuilderPreview.tsx` | preview card + buttons | renamed `PreviewConfirm.tsx`, gains TTS readback + voice-command parser |
| `StarterExamples.tsx` | 5 chips below text input | kept as the **fallback path** (visible when user opts into "печатать вместо голоса") |
| `BuilderPanel.tsx` | top-level | deleted (its functionality lives in `VoiceBuilderScreen.tsx` + the kept `StarterExamples.tsx`) |
| `builderApi` | start / answer / deploy / cancel | adds `extract`, `transcribe`, `say` |
| `useBuilderStore.start(text)` | always calls `/builder/start` | now calls `/builder/extract` first; falls back to `/builder/start` if extract returns `complete: false` AND the endpoint signals "no useful extraction" (or 5xx) |
| `kernel/main.py` builder endpoints | start / answer / deploy / cancel | adds `POST /builder/extract` |
| `kernel/main.py` voice endpoints | start / stop / status / clone (orchestrated pipeline) | adds `POST /voice/transcribe` (one-shot, bypasses pipeline) |
| Existing tests (`tests/kernel/test_builder_endpoints.py`, etc.) | green | stay green; new tests added alongside |

**Migration discipline:** the swap from `BuilderPanel.tsx` → `VoiceBuilderScreen.tsx` is one commit; the `useBuilderStore` extension is one commit; backend endpoints are two commits (one per endpoint). Each commit ships green tests.

---

## Scope

In:
- New L1-layout screen `VoiceBuilderScreen.tsx` mounted at `mode === "builder"`.
- Browser audio capture (MediaRecorder API) with push-to-talk + frontend VAD (1.5s of below-threshold RMS = stop). **Frontend-only VAD; no Phase 3 bridge dependency.** This keeps the pilot engine-independent of the Phase 3 `voice.engine: rust` cutover (Gate A).
- New backend endpoints `POST /voice/transcribe` (wraps existing whisper bridge op) and `POST /builder/extract` (LLM single-shot extraction).
- TTS readback for wizard questions and final preview via existing `POST /tts/speak`.
- Visual dual-track always on (transcript + spec card on screen — A2).
- Fast-path single-shot extraction (A4) with deterministic fallback to wizard.
- Final preview readback with voice-confirm (A6).
- Template-anchored question phrasing (A7) — minor edits to `wizard.py` question strings to surface template name in first question.
- Voice command parser for confirm / cancel / "поправь N" during `preview`.
- Manual text-input fallback path preserved (StarterExamples + a small `<input>` reachable via "печатать вместо голоса" link).

Out of pilot, deferred to v2 / future work:
- Per-step voice confirmation (A1 — A2 visual track is the safety net).
- STT confidence-gated re-prompt (A3).
- Voice barge-in during TTS (A5).
- localStorage state persistence across reload (server-side `SessionStore` TTL covers session loss).
- Existing agent remix ("переделать голосом").
- Hero CTA in Agent Store v2 (lives in #10 brainstorm; will navigate by calling `useAppStore.setState({ mode: "builder" })`).
- Global wake-word "hey jarvis, создай агента" → set mode (already partially wired in Phase 3 voice pipeline; spec doesn't touch that path).
- Custom Python agent generation (Tier 3 #18).

---

## Architecture

```
┌────────────────────── UI (React) ──────────────────────┐
│  mode === "builder" route                              │
│  ┌─ VoiceBuilderScreen.tsx (state machine owner) ──┐   │
│  │  ├─ VoiceOrb.tsx       (mic + pulse)            │   │
│  │  ├─ LiveTranscript.tsx (recent STT)             │   │
│  │  ├─ SpecCard.tsx       (accumulating spec)      │   │
│  │  ├─ WizardPrompt.tsx   (current question + TTS) │   │
│  │  ├─ PreviewConfirm.tsx (A6 final review)        │   │
│  │  └─ StarterExamples.tsx (kept as fallback)      │   │
│  └─ useBuilderStore (extended) ───────────────────┘    │
│  └─ builderApi (extended)                              │
└────┬────────────────┬─────────────────┬────────────────┘
     │                │                  │
     ▼                ▼                  ▼
 MediaRecorder   /voice/*           /builder/*
 + RMS-VAD       (Python:3005)      (Python:3005)
                ┌─────────────┐    ┌──────────────┐
                │ /transcribe │NEW │ /extract     │NEW
                │ /tts/speak  │ ✓  │ /start       │ ✓
                └─────────────┘    │ /answer      │ ✓
                                   │ /deploy      │ ✓
                                   │ /cancel      │ ✓
                                   └──────────────┘
```

The pilot does not depend on the Phase 3 `voice.engine: rust` cutover. Frontend-side VAD + direct HTTP STT/TTS = no contact with the orchestrated wake-word pipeline.

## State machine (extended `useBuilderStore`)

Phase enum (replaces existing):
```typescript
type BuilderPhase =
  | "idle"          // existing — pre-anything
  | "listening"     // NEW — mic active, capturing audio
  | "transcribing"  // NEW — audio sent to /voice/transcribe
  | "extracting"    // NEW — text sent to /builder/extract
  | "asking"        // existing — wizard mid-flow (TTS reading question OR mic listening for answer)
  | "previewing"    // existing — A6 readback in progress + voice/buttons for confirm/cancel/edit
  | "deploying"     // existing
  | "done"          // existing
  | "error";        // existing
```

Sub-states for `asking`:
```typescript
type AskingSubState = "tts_speaking" | "listening_for_answer";
```

Transition diagram:
```
idle ──tap mic──▶ listening ──VAD silence──▶ transcribing
                  │                          │
                  └─tap again─▶ idle         ▼
                                       extracting
                                            │
                              ┌─────────────┴─────────────┐
                              ▼                            ▼
                        complete=false                complete=true
                              │                            │
                              ▼                            ▼
                        asking(tts_speaking)         previewing(tts_speaking)
                              │ TTS done                  │ TTS done
                              ▼                            ▼
                        asking(listening_for_answer)  previewing(listening)
                              │ STT result                │ STT result parsed
                       ┌──────┴───────┐               ┌───┴───────┐
                       ▼              ▼               ▼           ▼
                       wizard advances   done=true   "да"→deploy  "поправь N"→
                       (back to TTS)     (preview)               asking at field N
                                                                 (back to TTS)
                                                          ▼
                                                       deploying ──▶ done | error
```

Owner: `VoiceBuilderScreen.tsx` listens to the store, dispatches actions; child components are presentational.

## Backend additions (Python)

### 1. `POST /voice/transcribe`
Thin HTTP wrapper around the existing whisper bridge op (`tts_worker.py::_handle_stt_transcribe`).

Request body (JSON):
```json
{
  "audio_b64": "<base64-encoded raw i16 LE PCM>",
  "sample_rate": 48000,
  "language": "ru"
}
```

Constraints:
- `audio_b64` length must be even (worker raises ValueError otherwise).
- `sample_rate` is the rate the browser actually captured at — **server resamples to 16 kHz**, so any rate works.
- `language` is a hint; pass `null` to auto-detect.

Response 200:
```json
{
  "text": "трекер воды каждые два часа",
  "language": "ru",
  "duration_ms": 2310
}
```

Errors:
- 400 `{"error": "audio_b64 required"}` — missing payload.
- 400 `{"error": "audio length not divisible by 2 (expected i16 LE)"}` — odd byte count.
- 500 `{"error": "<message>"}` — STT model failure or unexpected.

Implementation: instantiate (or reuse the FastAPI app-state-cached) `SpeechToText` from `kernel.voice.stt`, port the i16 LE PCM decode + `scipy.signal.resample_poly` 16 kHz resample logic from `tts_worker.py::_handle_stt_transcribe` (lines 143-199) into a small helper, call `stt._model.transcribe(audio_f32, beam_size=5, language=language, vad_filter=True)`, return `{text, language, duration_ms}`. **No bridge subprocess involved.** ~60-80 LoC including the helper. The same `SpeechToText` instance the Phase 3 in-process pipeline uses is shared via `app.state.stt` (already attached by the existing voice pipeline init), so first-request load cost is paid once at startup, not per transcribe.

### 2. `POST /builder/extract`
Single LLM call attempting to skip the entire wizard.

Request body:
```json
{ "request": "трекер воды каждые два часа с напоминанием в чат", "language": "ru" }
```

Response — fully extracted (`complete: true`):
```json
{
  "complete": true,
  "session_id": "abc123def456",
  "spec": {
    "name": "treker-vody",
    "description": "трекер воды каждые два часа с напоминанием в чат",
    "type": "skill",
    "template": "tracker",
    "config": { "interval": "2 часа", "goal": "?", "notify_channel": "чат" }
  }
}
```

Response — partial (`complete: false`):
```json
{
  "complete": false,
  "session_id": "abc123def456",
  "step": 1,
  "total_steps": 3,
  "next_question": "Какая дневная цель?",
  "partial_spec": {
    "name": "treker-vody",
    "template": "tracker",
    "config": { "interval": "2 часа", "notify_channel": "чат" }
  }
}
```

Note: even on `complete: false`, the endpoint returns a fully-formed `session_id` — created via `SessionStore.create()`, with extracted answers pre-loaded into `BuilderSession.answers`, and `session.step` advanced past the questions whose config keys are already populated. The UI proceeds with `/builder/answer` (using the returned `session_id`) starting from the first un-answered question. **No second `/builder/start` call.**

If LLM fails or returns invalid JSON → endpoint silently falls back to `BuilderFlow.start(request)` and returns the same partial-response shape with `step: 0` and full question list. UI never knows extraction was attempted; behaviour matches the existing text pilot.

**LLM system prompt (verbatim — keep this in `kernel/builder/extractor.py` as a module constant):**
```
You are KALI's skill spec extractor. The user describes a Russian (or
English) automation idea; your job is to extract every parameter that
can be derived from their words and return a complete or partial skill
spec.

Templates and their config keys:
- tracker:   interval (e.g. "2 часа", "час"), goal (e.g. "2 литра"), notify_channel ("голос" | "телеграм" | "чат")
- reminder:  interval, time_window (e.g. "9-22", "будни")
- monitor:   target (URL or service), interval
- notifier:  trigger, notify_channel
- logger:    categories

Use ONLY data the user provided. Do NOT invent values. If a parameter
is not stated, omit the key entirely (do not write null).

Respond with STRICT JSON only, no prose:
{
  "type": "skill",
  "template": "<one of: tracker | reminder | monitor | notifier | logger>",
  "name_hint": "<kebab-case slug, lowercase, ≤40 chars>",
  "extracted": {
    "interval": "<string>",
    "goal": "<string>",
    "notify_channel": "<string>",
    "time_window": "<string>",
    "target": "<string>",
    "trigger": "<string>",
    "categories": "<string>"
  },
  "confidence": <0.0-1.0>
}

Only include keys you actually extracted under "extracted".
```

**`BuilderSession` mutation contract (the missing detail from spec v1):**

After LLM returns `{template, name_hint, extracted}`, the endpoint:

1. Validates `template` against the registered list (`{"tracker", "reminder", "monitor", "notifier", "logger"}`). Mismatch → fallback to `start()`.
2. Calls `create_wizard(request, intent)` to produce the canonical question list for that template.
3. Stores `name_hint` (if present) on the session as `session.name_hint`. (New field on `BuilderSession` — `name_hint: str | None = None`.)
4. For each `(question, config_key)` pair in the wizard's expected schema (derived from the same Russian substring rules `_build_spec` uses — extracted into a shared `_question_to_key(q)` helper that both `_build_spec` AND `/builder/extract` import to stay in sync):
   - If `extracted[config_key]` is present → append the value to `session.answers` AND increment `session.step`.
   - If absent → stop iterating (don't fill later answers when an earlier one is missing — preserves wizard order).
5. Sets `session.spec = None` (preview not yet built).
6. If `session.step == len(session.questions)` (all extracted) → calls `_build_spec(session)` immediately, sets `session.spec`, returns `{complete: true, spec, session_id}`.
7. Else returns `{complete: false, session_id, step, total_steps, next_question, partial_spec}` where `partial_spec` is `_build_spec` applied to the partially-answered session (config keys mapped from the answers we have).

`_build_spec` is updated to prefer `session.name_hint` when present, falling back to the existing slugify-of-request when absent. The hint is run through `_slugify` regardless (defensive — guards against the LLM returning a non-kebab-case string). Connecting `name_hint` to the final name also mitigates the "STT mishears agent name" risk: even if the request transcript is messy ("трекер вода каждые два часа"), the LLM emits a clean slug ("treker-vody") because it parses intent rather than copying surface text.

**Test-case checklist for `_question_to_key`** (verify each question string in `_skill_questions` maps to its expected key — required during implementation):
| Template | Question | Expected key |
|----------|----------|--------------|
| tracker | "Какая дневная цель?" | `goal` |
| tracker | "Как часто напоминать?" | `interval` |
| tracker | "Куда отправлять уведомления — голосом или в телеграм?" | `notify_channel` |
| reminder | "Как часто напоминать?" | `interval` |
| reminder | "В какое время начинать и заканчивать?" | `time_window` |
| monitor | "Какой URL или сервис проверять?" | `target` |
| monitor | "Как часто проверять?" | `interval` |
| notifier | "При каком условии уведомлять?" | `trigger` |
| notifier | "Куда отправлять — голосом или в телеграм?" | `notify_channel` |
| logger | "Какие события записывать?" | `categories` |

These pairs become the unit-test parametrize input for `_question_to_key`. Drift in `_skill_questions` strings → test fails → forces sync.

The shared `_question_to_key(q)` helper lives in `wizard.py`:
```python
def _question_to_key(question: str) -> str:
    """Map a wizard question text to the config key its answer populates.

    Lowercases the question once at the top so substring needles are
    case-insensitive (the wizard questions start with capitalised words
    like "Куда" / "Какая").

    Order matters: `trigger` is checked BEFORE `notify_channel` because
    the notifier question "При каком условии уведомлять?" contains both
    "услов" (→ trigger, the right answer) AND "уведом" (→ notify_channel,
    a false match if checked first). Tighter or earlier matches win.
    """
    q = question.lower()
    if "часто" in q or "interval" in q:
        return "interval"
    elif "цел" in q or "goal" in q:
        return "goal"
    elif "услов" in q or "trigger" in q:
        return "trigger"
    elif "уведом" in q or "notify" in q or "куда" in q:
        return "notify_channel"
    elif "url" in q or "сервис" in q:
        return "target"
    elif "событ" in q or "категор" in q:
        return "categories"
    elif "врем" in q or "time" in q:
        return "time_window"
    else:
        return ""  # falls into param_N bucket downstream
```
`_build_spec` is updated to call this helper instead of inlining the substring checks (refactor in the same commit). The parametrized unit test below is the authoritative correctness check — drift in either the helper or `_skill_questions` strings makes it fail.

**LLM call routing:** uses `kernel.builder.agent_generator._call_llm` (already imported by `intent_classifier`). Provider auto-detected via `_detect_provider()`. No new LLM infra.

**Estimate:** ~1 day Python (extractor module + endpoint + tests + `_question_to_key` refactor).

### 3. Reuse existing endpoints
- `POST /tts/speak {text, language}` — synthesize + play through speakers, return when done. Used for wizard questions and A6 readback.
- `POST /builder/{start, answer, deploy, cancel}` — unchanged.

### 4. F5 prewarm at backend startup
Add a FastAPI startup hook (`@app.on_event("startup")` or `lifespan` context) that fires `tts_router.load_models()` once on boot. One-line change to `kernel/main.py`. Removes "first wizard question latency" risk; doesn't depend on per-session prewarming. (The previous spec proposed an empty-string `/tts/speak` call, which 400s — endpoint rejects empty text. Dropped.)

---

## Frontend components

### `VoiceBuilderScreen.tsx` (NEW — replaces `BuilderPanel.tsx`)
- Mounted at `mode === "builder"` in `App.tsx`.
- Owns the L1 layout: orb centered, transcript below, prompt below transcript, spec card below prompt.
- Subscribes to `useBuilderStore`, dispatches phase transitions.
- Hosts the global cancel handlers: ESC keyboard listener, focus-loss-on-route-leave, voice-cancel disambiguator.
- Renders `<StarterExamples>` only when `phase === "idle"` AND user has opened the "печатать вместо голоса" disclosure (small text-link bottom-right of orb area).

### `VoiceOrb.tsx` (NEW)
- Pulsing mic button with three visual states: `idle` (cyan ring), `listening` (saturated pulse), `processing` (rotating spinner overlay during `transcribing` / `extracting`).
- Tap toggles listening on/off.
- During `listening`, runs frontend RMS-VAD: every 50ms compute RMS over the last 100ms of audio frames; if below threshold for 1500ms continuously → state transitions to `transcribing`.
- Disabled during `extracting`, `deploying`, `done`.

### `LiveTranscript.tsx` (NEW)
- Renders the most recent STT result + the previous user turn (kept across `wizard-Q` → `wizard-A` → next `wizard-Q` so the user can see what was just heard while they listen to the next question).
- Old turns clear when phase returns to `idle` or after `success`.
- Read-only.

### `SpecCard.tsx` (NEW)
- Vertical list of `(label, value)` pairs.
- Pulls from store: starts empty, populates from `extract()` response (`partial_spec` or `spec`), gains a row per successful `answer()`.
- Empty fields shown muted ("Цель: ?"); filled fields highlighted.
- During `previewing`, gets a holographic-tokens accent glow to signal it as the readback target.
- Rows use existing `--j-*` color tokens — no hardcoded literals (matches Tier 2 #8 discipline).

### `WizardPrompt.tsx` (NEW — renames + extends old `BuilderProgress.tsx`)
- Displays the current wizard question.
- On mount + on question change, fires `say(question)` (calls `/tts/speak`).
- Hides during `extracting`, `previewing`, `deploying`, `done`, `error`.
- Includes step counter ("Шаг 2 из 3") at the bottom — replaces the old step-dots.

### `PreviewConfirm.tsx` (NEW — renames + extends old `BuilderPreview.tsx`)
- Active during `previewing` phase.
- Reads spec via `say(...)`: assembled from `spec.template`, `spec.name`, and the most-prominent `config` keys (template-specific format string).
- After TTS settles, transitions store to `previewing/listening` sub-state and starts capturing audio.
- Voice command parser (see "Voice cancel disambiguation" below for cancel-vs-content rule):
  - `да|подтверди|ставь|давай|запускай|поехали` → `deploy()`
  - `отмена|нет|не надо|останови|хватит` (under disambiguation rule) → `cancel()`
  - `поправь <field>|измени <field>|<field>` (matched against the spec's config keys) → re-enter `asking` phase at the question whose key matches the named field.
- Visible buttons mirror each voice command (a11y + non-voice fallback).

### `StarterExamples.tsx` (KEPT)
- Same 5 prefilled prompts as today.
- Visible only behind the "печатать вместо голоса" link (not by default in the L1 layout).
- Clicking a chip writes its text to a small `<input>` and submits via the existing `start()` action — preserves the text path for users without a working mic.

### `useBuilderStore` (EXTENDED, `ui/src/stores/builder.ts`)
- Phase enum extended (see State machine above).
- New actions:
  - `tap()` — orb tap; toggles `listening` ↔ previous phase.
  - `submitAudio(blob, sample_rate)` — sets phase to `transcribing`, calls `transcribe(blob)`, then `extract(text)`. Resolves into `previewing` or `asking` per response.
  - `voiceConfirm(intent: "yes" | "no" | "edit", field?: string)` — handles parsed voice command during `previewing`.
- Existing actions unchanged in signature; their internal phase transitions extend.

### `builderApi` (EXTENDED, `ui/src/api/builder.ts`)
- New: `transcribe(audio_b64: string, sample_rate: number, language?: string): Promise<{ text, language, duration_ms }>`.
- New: `extract(request: string, language?: string): Promise<ExtractResponse>` where `ExtractResponse` is the union `{ complete: true, session_id, spec } | { complete: false, session_id, step, total_steps, next_question, partial_spec }`.
- New: `say(text: string, language?: string): Promise<void>`.

### Browser audio capture details
- Uses `navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 48000, channelCount: 1, echoCancellation: true, noiseSuppression: true } })`.
- Records via `MediaRecorder` with mimeType `audio/webm;codecs=opus` initially; on stop, decodes via `AudioContext.decodeAudioData` to `Float32Array`, downconverts to `Int16Array` (i16 LE), base64-encodes, and submits.
- The browser's native sample rate is reported in `audioContext.sampleRate` and forwarded as `sample_rate` to `/voice/transcribe` — the worker handles resampling.
- Mic-permission denial → inline notice with link to settings + the "печатать вместо голоса" fallback link rendered prominently.
- First-mount of the screen on a session shows a one-time intro banner: "Чтобы говорить с Jarvis, нужен доступ к микрофону" + "Разрешить" button. Banner dismissed via localStorage flag.

---

## Voice cancel disambiguation

The risk: during `asking/listening_for_answer`, an STT result like "не надо в телеграм, отмена дай голосом" must be treated as **answer content**, not as a cancel command. The risk also exists during `previewing/listening` where short utterances like "отмена" should fire cancel.

Rule:
- During `previewing/listening` — voice command parser uses dedicated keyword matcher. Match cancel/confirm/edit ONLY when the matched word lies within the first or last 3 tokens of the trimmed STT result. Examples:
  - "да" → confirm ✓
  - "да ставь" → confirm ✓ (token at start)
  - "поставь да" → confirm ✓ (token at end)
  - "не надо отменять, продолжай" → no match (cancel keyword not at edges) → treat as edit hint, fallback to "поправь" matcher → no field match → ignore + repeat preview readback once.
- During `asking/listening_for_answer` — cancel command is recognised ONLY when the STT result is **at most 3 tokens** AND the entire utterance matches one of: `отмена | не надо | хватит | перестань | стоп | отменяй`. Anything longer (the user's actual answer to a wizard question) is forwarded to `/builder/answer` verbatim, regardless of substring contents.
- `idle` and other phases — cancel commands are ignored (nothing to cancel).

Edge case backstop: after a session is cancelled (whether by ESC, voice, or button), the `success` (well, `done` → in this case rendered as a "cancelled" affordance) state shows a small "Восстановить?" link for 30 seconds. Clicking it rehydrates the partial spec from server-side `SessionStore` (TTL 1800s). Catches the worst case where a false-positive cancel destroys 30s of work.

---

## Flow walk-through (golden path — A4 hits)

1. User clicks "Создать агента" in `Sidebar` → `useAppStore.setState({ mode: "builder" })`.
2. `VoiceBuilderScreen` mounts in `idle`. F5 already prewarmed at backend boot.
3. User taps `VoiceOrb` → `listening`. Browser captures audio at 48 kHz mono.
4. User says "трекер воды каждые два часа с напоминанием в чат" then stops. Frontend RMS-VAD detects 1.5s silence → orb stops, `submitAudio` fires.
5. `useBuilderStore` sets phase `transcribing`. `builderApi.transcribe(blob, 48000, "ru")`. Returns `{text: "трекер воды каждые два часа с напоминанием в чат", language: "ru", duration_ms: 2310}`.
6. Phase → `extracting`. `builderApi.extract(text, "ru")`. LLM returns `template: "tracker", extracted: {interval: "два часа", notify_channel: "чат"}`. Endpoint maps interval/notify_channel through `_question_to_key`, finds tracker has 3 questions, fills 2 of 3, leaves `goal` un-answered. Returns `{complete: false, session_id, step: 0, total_steps: 3, next_question: "Какая дневная цель?", partial_spec: {...}}`.
7. Wait — that's a partial. Let me redo with all three filled. Imagine user said "трекер воды два литра в день каждые два часа в чат". Now `extracted: {interval: "два часа", goal: "два литра", notify_channel: "чат"}`. All three filled → endpoint returns `complete: true, spec: {...}`.
8. Phase → `previewing/tts_speaking`. `PreviewConfirm` calls `say(...)` → "создаю «треker-vody», трекер на воду, цель два литра, интервал два часа, уведомление в чат — подтверди".
9. TTS settles. Phase → `previewing/listening`. Mic captures. User says "да".
10. STT returns "да". Voice command parser: `да` at first-3-tokens → confirm. `useBuilderStore.deploy()` fires.
11. `/builder/deploy` returns `{status: "deployed", name: "treker-vody"}`. Phase → `done`. Toast: "агент готов, попробуй: «сколько я выпил воды сегодня?»". Buttons: "К чату" / "Создать ещё".

## Flow walk-through (wizard fallback — A4 partial)

1-5 as above.
6. Endpoint returns `complete: false` with one missing field. Phase → `asking/tts_speaking`. `WizardPrompt` reads "Какая дневная цель?" via `say()`. SpecCard already shows interval and notify_channel filled.
7. TTS settles. Phase → `asking/listening_for_answer`. User says "два литра".
8. STT returns "два литра" (3 tokens — disambiguation rule says treat as answer content, OK because no cancel keyword at start/end). `/builder/answer` called with the text → `{done: true, preview: {...}}`. Phase → `previewing/tts_speaking`.
9-11 as golden path 8-11.

---

## Error handling

| Case | UX |
|------|----|
| Browser denies mic permission | Inline notice: "Разреши микрофон в настройках" + link, plus "печатать вместо голоса" disclosure pulled into prominence. |
| Mic permission revoked mid-flow | Toast + state → idle, banner same as above. |
| `/voice/transcribe` 400 ("audio length not divisible by 2") | Toast "ошибка распознавания, попробуй ещё раз", retry on the orb (state → idle). Browser reuses cached permission. |
| `/voice/transcribe` 500 (STT model load / inference failure) | Toast "распознаватель упал", retry button polls `/health` every 2s up to 10s; if persistent, push the "печатать вместо голоса" disclosure into prominence. |
| `/voice/transcribe` returns empty text | TTS "не услышал, повтори?" via `/tts/speak`, state → listening. |
| `/builder/extract` invalid response (5xx, JSON parse fail) | Frontend silently calls `/builder/start` with the same text — wizard takes over from step 0. |
| `/builder/extract` returns garbage template | Endpoint already validates server-side; falls back to `/builder/start`. UI never sees this case. |
| `/builder/answer` SessionNotFound (404) | Toast "сессия истекла", state → idle, partial spec discarded. |
| `/builder/deploy` returns `{status: "error", ...}` | Show backend message in `PreviewConfirm`. Buttons: "Поправить" (re-enter `asking` from step 0 with same `session_id`) / "Отмена". (No "Заменить with overwrite" — backend doesn't support it, dropped from UX.) |
| `/tts/speak` 5xx | Skip TTS this turn, render question text only, log warning. Wizard continues. |
| `/health` failing | Full-screen overlay "не могу связаться", retry button polls every 2s. |

---

## Cancel behaviour

Every cancel path (ESC, browser back, voice "отмена" within disambiguation rule, mode-switch via Sidebar, window close) calls `/builder/cancel` if `session_id` is present. The endpoint is idempotent. Server-side `SessionStore` TTL (1800s) catches abandoned sessions where a clean cancel didn't fire.

---

## State persistence

Server-side only. `BuilderSession` lives in `SessionStore`. UI reload mid-flow loses `session_id` from React state → effectively restart. The "Восстановить?" link (see disambiguation backstop) provides recovery within a single mount; cross-mount recovery via localStorage is deferred to v2.

---

## Tests

**Default test suite (must run on every PR / branch):**
- Vitest unit per leaf component (`VoiceOrb`, `LiveTranscript`, `SpecCard`, `WizardPrompt`, `PreviewConfirm`).
- Vitest integration for `useBuilderStore` against mocked `builderApi` — covers the full state machine (golden path + wizard fallback + cancel + each error case).
- Vitest e2e for `VoiceBuilderScreen` driving the state machine through golden + wizard + cancel + error (mocks `MediaRecorder` and `AudioContext`).
- Pytest unit for `kernel/builder/extractor.py::extract_spec`: deterministic LLM mock returning hand-crafted JSON for each template + degenerate cases (empty extracted, invalid template, missing required field).
- Pytest unit for `_question_to_key` (regression — both `_build_spec` and the extractor depend on it being canonical).
- Pytest endpoint tests for `/voice/transcribe` and `/builder/extract` (default suite): validate request shape (400 on missing/invalid payload), forward-to-bridge mock for transcribe, response JSON shape for extract. **HTTP shell behaviour, not ML behaviour.**

**Gated suite (`ml-tests` feature, opt-in):**
- Pytest integration `/voice/transcribe` against a real bridge worker (real Whisper, real audio fixture). Validates the audio framing round-trip end-to-end. Not run by default per the existing convention.

**Manual:**
- Live voice rehearsal as part of the dev-box pre-ship checklist. Five back-to-back skills created voice-only; success rate ≥ 4/5 to ship to friends.

---

## Estimate

7-8 days solo:

| Day | Surface |
|-----|---------|
| 1 | Backend: `_question_to_key` extraction + `extractor.py` module + `/builder/extract` endpoint + pytest unit + endpoint tests in default suite |
| 2 | Backend: `/voice/transcribe` endpoint + bridge wiring + tests; F5 prewarm in startup hook |
| 3 | Frontend: extend `useBuilderStore` (phases, actions, voice command parser); extend `builderApi` with `transcribe`, `extract`, `say` |
| 4 | Frontend: `VoiceOrb` + browser audio capture (MediaRecorder + AudioContext + RMS-VAD + downconvert + base64) |
| 5 | Frontend: `VoiceBuilderScreen` L1 layout + `LiveTranscript` + `SpecCard` + `WizardPrompt`; remove `BuilderPanel`/`BuilderProgress`/`BuilderPreview`; wire `StarterExamples` behind disclosure |
| 6 | Frontend: `PreviewConfirm` with TTS readback + voice command parser + cancel disambiguation rule |
| 7 | Error handling + cancel paths + first-mount mic-intro banner; tests round-up |
| 8 | Polish + manual rehearsal + handoff doc |

Days 1-2 (backend) and 3-7 (frontend) can interleave — frontend dev box can hit a stub endpoint that returns canned `complete=true` responses while the real backend extractor is in progress.

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LLM extraction (A4) hallucinates wrong template | Med | Server-side validation against the registered template list; on mismatch fall back to `start()`. Pytest covers each template + invalid-template case. |
| LLM extraction hits timeout / 5xx | Med | Endpoint catches all exceptions and falls back to `start()`. UI never sees the difference. |
| STT mishears agent name → wrong skill identifier | Med | Generated `name` is `_slugify`-cleaned. Preview readback names the slug verbatim — user catches it audibly + visibly on the spec card. |
| Frontend RMS-VAD too aggressive (cuts off slow speakers) | Med | Threshold + window size tunable as constants; manual rehearsal is the QA loop. If chronic, fall back to "tap mic to stop" as default + auto-stop opt-in. |
| Frontend RMS-VAD too lenient (background noise prevents stop) | Med | Calibration step on first mic-permission grant: 1-second silence baseline → threshold = baseline × 3. Stored in localStorage. |
| Voice cancel false positive (mishears answer as cancel) | Low (with rule) | Disambiguation rule: cancel keywords only matched at start/end of ≤ 3-token utterances during answer phase. "Восстановить?" backstop covers the residual. |
| F5 cold-load on first wizard question feels slow | Low | Backend startup hook prewarms F5 (`tts_router.load_models()`) before serving any traffic. |
| Browser MediaStream permission UI jarring on first use | Med | One-time intro banner on first `/builder` mount + localStorage flag to suppress on subsequent mounts. |
| Existing AgentStore / Settings / Chat tests regress because of `useBuilderStore` extension | Low | Extending phases is additive; existing actions keep their signatures. CI catches the rest. |
| Public-launch first impression hinges on this screen | High | Multi-day manual rehearsal before friend distribution; success-rate gate (≥ 4/5 voice-only runs). Cut friend rollout if rate falls below. |
| `SpeechToText` model fails to load (missing weights, GPU OOM) | Low | Endpoint surfaces the underlying exception as 500 with a structured error message. UI shows toast + retry button. Same failure mode as the existing in-process voice pipeline; not specific to this endpoint. |

---

## Success criteria

- Non-tech first-time user (Vasily acting as proxy) creates first skill in ≤ 60 seconds from `mode === "builder"` mount, voice-only path, no fallback to text input.
- A4 fast-path single-shot lands `complete: true` on ≥ 60% of "трекер X каждые N часов в Y" pattern utterances during rehearsal.
- Zero broken states: every error path has a visible recovery action; no dead ends.
- Default test suite stays green throughout. UI vitest count grows by ~12-15 cases. Pytest count grows by ~10 cases (extractor + endpoint shells). No regressions in existing AgentStore / Settings / Chat / existing builder tests.
- Manual rehearsal: 5 voice runs back-to-back without restart → ≥ 4 deployed skills (success-rate gate). Each run < 60s wall clock; total session < 6 min.

---

## What this unblocks

- **Tier 2 #10 (Agent Store v2) hero CTA** dispatches `useAppStore.setState({ mode: "builder" })` and lands on a working voice-first creator surface.
- **First public-launch demo material** — voice creation in a 15-second reel, no edits.
- **Friend-test loop iteration** — once the first agent is created, the surface to create the second is identical, which makes "same friend trying multiple things" a natural UGC arc.

## What this does NOT unblock (intentionally)

- Custom Python agent creation (Tier 3 #18).
- Multi-modal agents (camera, screen capture).
- Builder-from-Reels (parse a friend's spec from a shared video).

These wait for stronger foundations — the pilot proves the voice path works for templated skills first.
