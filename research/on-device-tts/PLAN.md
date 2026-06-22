# On-device Russian TTS — R&D plan (KALI 2.0 voice)

> **Status:** groundwork. Approach details (distillation method, exact base
> model) get refined by the running deep-research (`w108hw119`). Everything here
> is approach-agnostic foundation: the goal, the data strategy, the eval
> protocol, the milestones, and the compute/license reality.

## Goal
A **high-quality Russian TTS that runs fully on-device** (phone + laptop, no
CUDA), with **weights we own** — so we simultaneously: (1) hit the on-device
v2.0 vision, (2) remove the **CC-BY-NC** license blocker (F5-TTS *code* is MIT;
the released *weights* inherit a non-commercial dataset license, and our
`v4_winter` finetune inherits that), and (3) keep voice off the cloud.

Two separable sub-projects:
- **A. Own the voice (quality + license):** finetune/train an F5-architecture
  model on Russian data we own/permissively-license → owned, license-clean weights.
- **B. Make it fast on-device (speed):** few-step distillation + quantization +
  per-platform export (ONNX/CoreML/ExecuTorch). The teacher is a good F5; the
  student runs in 1–4 steps on a phone NPU/CPU.

These are independent: B can be proven on the *existing* checkpoint before A
delivers an owned voice.

## Why it's reachable
F5-TTS = flow-matching with a Diffusion-Transformer (DiT) + ConvNeXt text
encoder → mel → Vocos vocoder. ~336M params. It is "slow" only because of
**NFE sampling steps** (≈16–32 DiT passes per utterance). Distilling to 1–4
steps is the single biggest on-device lever, and the code/architecture is open
(MIT). Compute is modest: finetuning/distilling a 336M model fits on one
high-end GPU (rented A100/4090/H100, hours–days per run).

---

## DATA — what, how much, quality vs quantity

**TTS data = aligned `(text, audio)` pairs.** The honest rule:
**quality dominates, above a quantity floor.** For Russian specifically, the
**highest-leverage quality dimension is transcription + stress (ударение)
accuracy** — misaligned text or wrong stress poisons a TTS model faster than
extra hours help (this is the «готОв» class of bug we already fought).

### Two data regimes
| Regime | Purpose | How much | Quality bar |
|---|---|---|---|
| **Hero voice** (the owned "Jarvis" voice) | one premium speaker we own | **~5–15 h clean single-speaker** (F5 is pretrained → we *adapt*, not train from scratch; 1–5 h already usable, 10–20 h excellent) | studio/quiet, 24 kHz, single mic, no clipping/noise/reverb; **exact transcripts**; consistent **correct stress** (RUAccent); numbers/dates/abbrev. normalized to spoken form |
| **General robustness** | broader RU pronunciation/prosody coverage | **~50–500 h diverse clean** (finetune, not from-scratch) | clean + correctly labelled; multi-speaker OK |

**Verdict on quantity vs quality:** for the hero voice, **10 h pristine beats
200 h noisy.** Quantity matters only for *coverage* (phonemes, prosody, domains)
once cleanliness is satisfied.

### For sub-project B (distillation) — data-light
Distillation uses the **teacher model's own outputs** as targets, so it needs
**little new audio** — mostly **diverse input TEXT** for coverage. The
on-device-speed work is cheap on data; the voice-quality work (A) is where audio
data matters.

### Sourcing (license-clean is the point)
- **RUSLAN** — single-speaker Russian, ~22 h, purpose-built for TTS, clean →
  best *public* starter for a baseline + first distillation runs.
- **Common Voice RU** (CC0) — multi-speaker, crowd-sourced; good for robustness
  but **variable quality → heavy filtering needed**; not for the hero voice.
- Others to vet for license: MLS-RU, Golos (Sber), SOVA, OpenSTT, M-AILABS RU.
- **Own recording = the gold path for the hero voice:** a voice actor (or a
  chosen KALI voice) reading a phonetically-balanced + KALI-domain script in a
  quiet room. **~5–15 h studio → an owned, license-free, premium voice.** Zero
  CC-BY-NC risk. This is the recommended path to ship a commercial voice.

### Concrete data sequence
1. **Phase 1 (zero new data):** RUSLAN + existing F5 RU checkpoint → baseline +
   first distillation experiment. Proves on-device feasibility before spending on data.
2. **Phase 2 (own voice):** record ~5–15 h clean Russian → finetune → owned
   license-clean hero voice.
3. **Phase 3 (optional):** filtered Common Voice RU for robustness.

---

## EVAL protocol (you can't improve what you don't measure)
A fixed Russian **eval set** (`eval_set.jsonl`) across categories: phonetic
coverage · **stress-test words** (the «готОв» class) · KALI-domain phrases
(weather/currency/agent-confirm/times/numbers) · prosody (questions/emphasis) ·
normalization (dates/abbrev.).

Metrics (`metrics.py`, `run_eval.py`):
- **Intelligibility:** WER/CER via STT round-trip — synthesize → transcribe with
  our Whisper → compare to input (catches dropped/garbled words + many stress errors).
- **Speed / on-device readiness:** **RTF** (real-time factor = synth_time /
  audio_duration) at different NFE steps, on **CPU vs GPU**, + model size at
  fp16/int8/int4. This is the on-device gate.
- **Quality (subjective):** blind A/B listening (your ears) on the eval set;
  optionally an automatic MOS predictor (UTMOS/DNSMOS) as a proxy.
- **Speaker similarity** (for the hero voice / cloning fidelity) via a
  speaker-embedding model.
- **Stress accuracy:** the stress-test subset, judged by listening (and partly
  by the STT round-trip). Russian-specific, highest-leverage.

Every milestone reports: **WER · RTF(CPU) · size · listening verdict.**

---

## MILESTONES (cheapest verifiable experiment first)
- **M0 — measure the bar.** Stand up the eval harness; measure the *current* F5
  RU: WER, RTF on CPU (the on-device gap), size. Establishes baseline + target.
- **M1 — few-step distillation probe (cheapest "is it feasible").** Distill the
  current teacher to 4 steps; measure quality drop vs RTF gain on CPU. Go/no-go
  signal for on-device.
- **M2 — quantize + export.** int8 + ONNX/CoreML/ExecuTorch; run on a *real
  device*; measure RTF + size + quality.
- **M3 — own the voice.** Record/source clean RU; finetune the hero voice →
  license-clean premium voice (and re-run eval).
- **M4 — full on-device pipeline.** Distilled + quantized + exported + owned
  voice; real-device eval; wire into the swappable router (on-device ↔ cloud
  degrade) as the local TTS tier.

Each milestone is independently shippable + measured; degrade gracefully
(on-device ↔ cloud) so nothing regresses for users.

## Compute & cost (modest)
One high-end rented GPU (A100/4090/H100), hours–days per run; ~$0.5–2/GPU-hr
cloud. Distillation + finetuning of a 336M model is well within a single-GPU
budget. No giant cluster needed.

## License strategy (the strategic kicker)
Build toward **owned weights** (F5 arch = MIT) trained on **owned/permissive
data** → removes the CC-BY-NC blocker for the paid product AND gives on-device.
One investment, three wins: on-device + license-clean + cloud-independent.

## Risks (honest)
- Few-step distillation while **preserving Russian stress** (hard-won) may drop
  quality — iterative.
- Mobile export of the DiT + ODE loop has engineering friction (custom ops, NPU
  gaps).
- "Acceptable on-device" is an open question our M0–M2 experiments answer; may
  end up tiered by device (flagship full-on-device, mid-range hybrid).

## Files in this track
- `PLAN.md` — this plan.
- `eval_set.jsonl` — the fixed Russian eval set.
- `metrics.py` — pure metric functions (WER/CER/RTF/normalize) — unit-tested.
- `run_eval.py` — the eval runner (wires synth + STT hooks to KALI's engines).
- `test_metrics.py` — tests for the pure metrics.
