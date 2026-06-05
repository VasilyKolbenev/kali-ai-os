# Voice Latency Optimization — Plan (2026-06-03)

**Goal:** minimize *perceived* voice latency — **TTFA (time-to-first-audio):** from "user stops speaking" → first response audio plays. That is what a person feels, not total round-trip.

**Targets:** TTFA **cloud < 600 ms, local < 1 s** (measured end-of-speech → first audio).

## Latency map (current pipeline)
```
endpoint-silence (~700 ms) → STT (Whisper) → LLM (/chat — FULL response awaited)
  → TTS (F5, ~3 s/sentence, non-streaming) → playback
```
Dominant contributors: **TTS first-audio** (F5 ≈ 3 s) and **LLM full-response wait**. STT + endpointing are secondary.

## Phases (highest-leverage first)
- **P0 — Measure.** Per-stage timing instrumentation + a reusable baseline benchmark (`scripts/measure_voice_latency.py`): STT, LLM, TTS stage times on fixtures. Establish the breakdown before cutting. *(solo, now — no mic needed)*
- **P1 — Stream LLM→TTS by sentence.** Token-stream the LLM; synthesize + play each sentence as soon as it completes while the LLM keeps generating. Overlaps LLM + TTS + playback → perceived = TTFA, not total. The client already consumes `voice.tts_chunk` events; the server must emit chunks per-sentence instead of one big synthesis. *(biggest win; cleanest in the Rust pipeline post-Gate-A)*
- **P2 — Fast streaming TTS.** Benchmark F5 first-chunk vs **Cartesia / Kokoro** (fold into the OmniVoice eval spike); adopt the fastest first-audio path for the cloud route. Keep F5 as the quality / local path.
- **P3 — Streaming STT + endpointing.** Partial transcripts to start the LLM sooner; tune the conservative ~700 ms silence window.

## Constraints
- Don't sacrifice RU voice quality — F5 stays as the quality path.
- Anti-pivot: voice-first companion; the local path stays private (no forced cloud).

## Success criteria
- TTFA **cloud < 600 ms, local < 1 s** (end-of-speech → first audio).
- A/B: baseline vs post-optimization via the benchmark + per-stage logs.

## Key files
- `kernel/voice/{pipeline,remote_pipeline}.py` — pipeline stage flow
- `src-tauri/src/backend/voice/{pipeline,state,tts}.rs` — Rust pipeline (post-cutover home for P1)
- `kernel/llm_router.py` — needs token-streaming for P1
- `kernel/voice/tts_router.py` — TTS synth (per-sentence for P1; streaming for P2)
- `scripts/measure_voice_latency.py` — NEW benchmark (P0)

## Sequencing vs roadmap
P0 now (solo, low-risk). P1–P3 land cleanest in the Rust pipeline **after the Gate A `engine=rust` cutover** (native stage-overlap), but design + baseline numbers start now.
