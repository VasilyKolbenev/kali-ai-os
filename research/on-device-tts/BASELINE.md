# M0 baseline — current F5 RU, on-device readiness

> The cheapest verifiable experiment from [PLAN.md](PLAN.md): measure the *bar*.
> Wire the eval harness ([run_eval.py](run_eval.py)) to KALI's real engines
> ([run_m0.py](run_m0.py)) and measure the current F5 Russian fine-tune —
> **WER · RTF(CPU) · size** — to establish the baseline and size the on-device gap.

## Setup (what was measured, exactly)

- **Synth:** KALI's live F5 path — `kernel.voice.tts_engine_f5.generate_audio`
  (checkpoint `f5_russian_accent_tune.safetensors`, ref `jarvis_ref_v2.wav`,
  NFE=32, cfg=2.0, speed=1.0), including the full text→audio pipeline
  (RUAccent stress + number normalization + sentence chunking). 24 kHz out.
- **STT round-trip:** KALI's faster-whisper (`SpeechToText`, model **`base`** —
  the default voice STT per `kernel/voice/pipeline.py` ← `models.py:163`),
  with KALI's domain `initial_prompt` + VAD. F5's 24 kHz is resampled to 16 kHz
  (librosa) before transcription.
- **Eval set:** 29 RU sentences across 5 categories ([eval_set.jsonl](eval_set.jsonl)):
  stress (10) · phonetic (4) · kali_domain (6) · prosody (4) · normalization (5).
- **Metric methodology:** WER/CER via STT round-trip (synthesize → transcribe →
  compare to the spoken-form reference; [metrics.py](metrics.py), Russian
  normalization folds ё/stress/punct). RTF = synth_time / audio_duration. A
  **warmup synth** runs before any timed item so the first item isn't a
  cold-start (CUDA compile / lazy-init) outlier.
- **Device:** GPU = RTX 5070 Laptop (torch cu128). CPU = same box with
  `CUDA_VISIBLE_DEVICES=-1` (F5 + Whisper both on CPU) — the on-device emulation.
  Raw outputs: [runs/gpu/](runs/gpu/), [runs/cpu/](runs/cpu/). 0 synth errors.

## Results

| device | WER | CER | RTF (mean) | RTF (median) | wall |
|---|---|---|---|---|---|
| GPU (RTX 5070) | 0.166 | 0.064 | 2.42 | 2.42 | 232 s |
| **CPU** (on-device proxy) | 0.154 | 0.066 | **72.9** | **39.7** | 101 min |

Per-category (CPU):

| category | n | WER | CER | RTF |
|---|---|---|---|---|
| stress | 10 | 0.140 | 0.048 | 112.1 |
| phonetic | 4 | 0.247 | 0.058 | 32.3 |
| kali_domain | 6 | 0.107 | 0.097 | 38.9 |
| prosody | 4 | 0.050 | 0.019 | 109.6 |
| normalization | 5 | 0.244 | 0.105 | 38.6 |

## Headline findings

1. **Intelligibility is solid and device-independent.** WER ≈ **0.15–0.17**
   (CPU 0.154 ≈ GPU 0.166 — the tiny delta is F5 sampling nondeterminism; same
   weights → same audio). This *validates the measurement*: RTF is what changes
   across devices, intelligibility is not. Best category = prosody (short emotive
   lines round-trip near-perfectly); worst = **normalization (0.24)** and
   **phonetic (0.25)** — the dates/times/№/% spoken-form items and the dense
   consonant-cluster tongue-twisters. (Round-trip conflates TTS + STT errors;
   see caveats.)
2. **Speed is the binding constraint — and the gap is large.** CPU RTF ≈ **73
   mean / 40 median**, **~30× slower than GPU**, and **~40–73× above the
   on-device target of RTF < 1** (faster-than-real-time, needed for streaming).
   RTF scales inversely with utterance length (fixed per-synth overhead): short
   stress/prosody lines ~110, long phonetic ~32. The mean (73) is inflated by
   short-utterance overhead; the **median (~40)** is the more representative
   typical cost.
3. **Size:** F5 checkpoint = **1.35 GB (fp32, 336 M params)** + vocos vocoder
   ~54 MB. Quantization projections (the on-device size levers): fp16 ~674 MB ·
   int8 ~337 MB · int4 ~168 MB. (Research baseline `f5-tts-mlx` 4-bit = 223 MB.)

## The gap — what M1 must buy

To reach RTF < 1 on CPU we need a **~40–73× speedup**. The available levers,
roughly:

- **Few-step distillation** (the biggest lever): NFE 32→4 ≈ ~8×, 32→2 ≈ ~16×.
- **Quantization:** int8 ≈ ~2× (plus CPU int8 kernels), int4 more on memory.
- Combined (NFE→2-4 + int8) realistically ≈ **16–32×** on this architecture.

So distillation + quant of *this* architecture likely lands at **RTF ≈ 2–5 on a
laptop CPU** — a 10–30× win, but **still short of < 1**, and a phone CPU is
worse. Honest implication (matches the [research digest](RESEARCH-2026.md)
"partial on phones"): full-quality F5 fully on a *CPU* is hard. On-device
viability probably needs one of: a **smaller distilled student** arch, **NPU/GPU
acceleration on-device** (not pure CPU), or a **tiered** rollout (flagship
on-device ↔ mid-range hybrid/cloud). M1 (few-step distillation probe on a rented
GPU) measures exactly how far the biggest lever gets us.

## Caveats (honest)

- **Round-trip conflates TTS + STT.** A WER hit may be a synth error *or* a
  Whisper mishearing (e.g. observed «высоко»→«высокая», «сэр»→«сыр»). The saved
  WAVs disambiguate by ear.
- **STT = `base`** (KALI's default voice STT). `small` (used in
  `transcribe_helper.py`, shipped in the stage) is more accurate → real WER is a
  touch *better* than reported. A known lever, not a baseline error.
- **The normalizer is in the loop.** norm-* items test KALI's number/date
  normalization too, not only F5 — which is correct (it's the shipped path).
- **CPU here = a laptop CPU**, not a phone NPU. Directional, not a phone number.

## Listening verdict (your ears)

Per-utterance WAVs saved to [runs/gpu/audio/](runs/gpu/audio/) (`<id>.wav`,
matching `eval_set.jsonl` ids). The subjective + stress-accuracy verdict (the
«гот+ов» class) needs blind listening — recommended focus: the `stress-*` and
`prosody-*` clips.

## Next

- **M1 — few-step distillation probe** (rented GPU): distill the current teacher
  to ~2–4 steps, re-run this harness, measure the RTF win vs quality drop. Go/no-go
  signal for on-device feasibility.
- Re-run this baseline with STT=`small` for a tighter intelligibility reference
  (optional; RTF is unaffected).
