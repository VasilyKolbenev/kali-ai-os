# OmniVoice TTS Evaluation Spike — design spec

> Status: spike spec, draft v1. Created 2026-05-13.
> Roadmap slot: Tier 2 P1 spike (parallel track, not blocking).
> Estimated 1 day (~6 working hours).
> Driven by: 2026-05-13 candidate technology scan — OmniVoice released v0.1.5 on Apr 28, 2026.

## One-line summary

Empirically evaluate **k2-fsa/OmniVoice** (646-language zero-shot TTS, Apache 2.0, ~2.46 GB model) as a candidate replacement for the current F5-TTS Russian engine. Decide swap / wait / skip after one day of hands-on benchmark — no premature commitment.

## Why this spike exists

The current TTS stack (`kernel/voice/tts_router.py`) routes to `f5_russian` on GPU + `elevenlabs` on cloud fallback. F5-TTS works in production after Premium v2 fixes (Apr 29). However a new open-source TTS released Apr 28, 2026 with claimed advantages on three axes we care about:

| Axis | F5-TTS (current) | OmniVoice (candidate) |
|---|---|---|
| Russian training data | small ru-fork corpus | **20 338.5 hours** baked into base model |
| Speed (RTF) | ~3-5× realtime typical | **~40× realtime** claimed (RTF 0.025) |
| Languages | Russian-only fork | **646 languages** in one model |
| License | CC-BY-NC-4.0 (fork-dependent) | **Apache 2.0** (commercial OK) |
| Model size | ~1.2 GB checkpoint + ~85 MB vocos | **~2.46 GB** safetensors |
| Voice control | reference-driven only | gender / age / pitch / dialect attributes |
| Apple Silicon | none | MPS supported |
| Streaming | none | **none** (red flag — only full utterance) |
| Maturity | proven in KALI prod | **8 days old** (v0.1.5 Apr 28) — red flag |

The headline numbers are attractive but unverified for our use case (Russian briefing voice, ~30-200 char utterance, RTX-class GPU, Windows). This spike resolves "claim vs reality" in one day.

## Non-goals (binding for this spike)

- **NOT a swap.** Result of spike = data + recommendation, not a refactor PR.
- **NOT a mobile/Tier 4 evaluation.** Same model on desktop only. Mobile evaluation happens during Tier 4 mobile arch spec (separate item).
- **NOT a F5-TTS removal.** F5 stays bundled in Premium v2 regardless of outcome — fallback is non-negotiable.
- **NOT a benchmark of all 646 languages.** Russian only. English secondary if time permits.

## Anti-pivot rule check

OmniVoice is voice infrastructure. **Does not violate** the v2.14 anti-pivot rule (no dev/design integrations). Swap consideration is purely engineering trade-off (quality / latency / size / license), not category drift.

## Gates on / depends on

**Gates on:**
- Premium v2 install complete (current TTS works → comparable baseline available).
- RTX GPU available locally (no cloud evaluation).
- Working microphone + reference audio sample (re-use F5's reference WAV: `models/voice/reference.wav`).

**Does NOT gate on:**
- Tier 2 #10 Agent Store v2 — orthogonal.
- Tier 2 #10.5 Proactive KALI v1 — orthogonal (proactive briefing TTS works on either engine).
- Gate A (Rust voice cutover) — TTS swap independent of orchestration engine.
- Mobile Tier 4 — re-evaluate then with different criteria.

## Method (1 day total)

### Step 1: Isolated install (1.5 h)

- Create separate venv: `.venv-omnivoice/` (do NOT pollute KALI's main `.venv`).
- Install: `pip install omnivoice` (verify package name on PyPI first; if unavailable, `pip install git+https://github.com/k2-fsa/OmniVoice.git`).
- Verify PyTorch 2.8.0 + CUDA 12.8 (cu128 already proven in KALI for RTX 50-series).
- Download model `k2-fsa/OmniVoice` (~2.46 GB).
- Confirm GPU recognized: `python -c "import torch; print(torch.cuda.get_device_name(0))"`.
- Smoke test minimal English example from README.
- **Time-box:** if install fails on Windows after 1.5 h → mark `install_failed` and skip to recommendation = "wait 30 days for community Windows fixes".

### Step 2: Russian quality A/B (2 h)

- Re-use F5's reference WAV (`models/voice/reference.wav`) and its ref text (`models/voice/reference.txt`).
- 5 test phrases (proactive-briefing style, varied lengths):
  1. *"Доброе утро. Сегодня плюс три, две встречи в одиннадцать и в три."* (briefing intro)
  2. *"Биткоин минус два процента за ночь. Не критично."* (alert phrase)
  3. *"Я заметил, ты часто спрашиваешь курс. Создать агента?"* (suggestion)
  4. *"Water-tracker напомнит выпить стакан в десять и в четырнадцать."* (notification)
  5. *"Хорошего дня, сэр."* (short closer)
- Generate each phrase with both engines on same reference voice.
- Save outputs: `bench_outputs/{f5,omni}_phrase_{1-5}.wav`.
- Self-grade subjective quality 1-5 per phrase per engine (naturalness / speaker similarity / clarity).
- Record any obvious artifacts (mispronounced loanwords, robotic prosody, dropped phonemes).

### Step 3: Latency + VRAM (1 h)

- Time generation per phrase: `time.perf_counter()` wrapper. Record p50 + p99 across 5 runs of phrase 1.
- VRAM peak: `nvidia-smi --query-gpu=memory.used --format=csv` snapshot every 100 ms during generation.
- Compare against F5 baseline measured the same way.
- Confirm cold-start time (first generation after model load) and warm-start time (subsequent generations).

### Step 4: Integration prototype (0.5 h, optional)

- Sketch `kernel/voice/tts_engine_omnivoice.py` with same interface as `tts_engine_f5.py` (read existing file first to mirror).
- Do NOT wire into router. Just confirm interface compat is feasible.
- If interface diverges significantly (e.g., requires async-different signature or different ref-audio format) → flag in report.

### Step 5: Document + recommend (1 h)

Write `memory/feedback_omnivoice_eval.md` with:

- **Verdict:** `swap` / `wait_60d` / `skip` — exactly one of these three.
- **Verdict rationale:** 3-5 sentences.
- **Quality scores table:** F5 vs Omni, per phrase, subjective 1-5.
- **Latency table:** p50/p99 per engine.
- **VRAM peak:** GB per engine.
- **Integration assessment:** complexity 1-5 (1 = drop-in, 5 = major refactor).
- **Risks observed:** specific (e.g., "loanword 'биткоин' pronounced 'битcoin' with English phonemes" if observed).
- **Re-evaluation trigger:** what would flip the verdict (e.g., "if v0.2.0 ships streaming inference, re-evaluate").

## Decision matrix (binding)

| Verdict | Means | Next action |
|---|---|---|
| **`swap`** | Omni clearly beats F5 on ≥2 of {quality, latency, size} with no critical regressions | Add `Tier 2 #10.6 — F5 → OmniVoice migration` to roadmap (~2-3 day effort). Gates after Proactive KALI v1 ships. |
| **`wait_60d`** | Parity or mixed results — could go either way pending API stability | Re-evaluate after 2026-07-13 (60 days). Document specific deciders. No roadmap change. |
| **`skip`** | F5 wins on ≥2 axes OR Omni has critical regression (broken Russian / install failure / instability) | No further action. Document why. Re-evaluate only if user reports F5 quality complaints. |

## Out of scope (parked for v2 evaluation if `wait_60d`)

- Streaming inference (Omni doesn't support yet — wait for v0.2+).
- int4/int8 quantization (none exists yet — wait for community).
- Voice cloning fine-tuning (zero-shot only in v0.1.5).
- Multi-speaker evaluation (we only need one Russian voice for KALI / Jarvis persona).
- English language evaluation (defer until KALI considers English launch).
- Cross-platform (Linux / macOS) — desktop Windows is the only Premium target for now.

## Success criteria

After this spike ships:
- `memory/feedback_omnivoice_eval.md` exists with one of three verdicts.
- All 5 Russian phrase output WAVs saved to `bench_outputs/` (gitignored — local artifacts).
- Roadmap entry created if `swap` chosen.
- 1 day elapsed real time (max 2 days if install friction).

## Open questions (resolve during spike)

1. **PyPI package name** — is it `omnivoice` or `k2-fsa-omnivoice` or git-only?
2. **Windows install** — does `pip install omnivoice` work on Windows + cu128 + RTX 50-series? (No community signal yet.)
3. **Reference audio format** — does Omni accept 24 kHz mono WAV like F5, or different sample rate?
4. **Cold start time** — model load duration on first call. If > 10 sec → bad for proactive briefing UX.
5. **Russian loanword handling** — does Omni handle Anglicisms ("биткоин", "лайк", "пост") naturally, or fall back to English phonemes?

## Risk register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Install fails on Windows | medium | high | Time-box 1.5 h, skip to `wait_60d` verdict |
| Russian quality worse than F5 | medium | low | Honest assessment → verdict `skip` |
| VRAM > 8 GB → can't fit alongside other KALI ML | low | high | Document peak → verdict `skip` for desktop, defer to Tier 4 cloud |
| Subjective quality bias (own assessment) | high | low | Document outputs in `bench_outputs/` for later re-listening |
| Time slip beyond 1 day | medium | low | Stop at end of day with whatever data collected, write partial report |

## Migration notes

- No code changes to `kernel/voice/tts_router.py` during spike.
- No new dependencies in main KALI `.venv`.
- No commits to `main` branch — work entirely in `.venv-omnivoice/` and `bench_outputs/`.
- Spike output is one new memory file only.

---

*Spike to be executed in one focused day. Decision deadline: ≤2 days from start. If `swap` verdict chosen, separate migration spec written before any code changes.*
