# On-device Russian voice AI — 2026 research digest

> Synthesized from a deep-research pass (25 sources fetched → 123 claims → 25
> adversarially verified, 18 confirmed / 7 killed). Cited + vetted. Re-benchmark
> at build time — the RU LLM landscape moves monthly.

## Verdict
Fully on-device Russian voice in 2026: **feasible on laptop/desktop, partial on
phones.** STT is essentially solved; LLM is tier-dependent; **TTS is the binding
constraint — and the constraint is as much LICENSING as quality/latency.** The
phone tier (Android NPU, on-device RU TTS latency) is the least-evidenced part —
our own spikes must answer it.

## STT — the most mature pillar 🟢
- **GigaAM2 CTC+LM = 8.42% WER** (Sber/Salute, **MIT**) tops an independent
  13-model/12-dataset Russian leaderboard — ~2× better than stock Whisper
  large-v3 (16.21%). [alphacephei/Vosk leaderboard; arXiv 2506.01192]
- Whisper-class (~1B) runs **real-time-plus on-device** on Apple Silicon ANE
  (WhisperKit; tens-of-× real-time — but English figures, don't generalize to RU
  or phones). [arXiv 2507.10860]
- ⚠️ **WhisperKitAndroid deprecated/archived Jan 24 2026**, no shipped successor
  → plan Android STT on **whisper.cpp / native LiteRT**, not the Argmax SDK.
- Open Q: can GigaAM2 (accuracy leader) actually run real-time on a *phone*, or
  is the deployable choice Whisper-family (proven runtimes, ~2× worse RU WER)?
- **Pick:** GigaAM2 (MIT) where it deploys; whisper.cpp as the portable fallback.

## LLM — generational jump, tier-split 🟡
- Edge RU quality leapt: Gemma-2-9B 69.2, Qwen2.5-14B 70.5 vs Qwen2-7B 37.5 on
  ru_llm_arena. [github VikhrModels/ru_llm_arena] (⚠️ last updated ~Oct 2024 —
  omits Qwen3/Gemma3; **re-benchmark at build time**.)
- **YandexGPT-5-Lite-8B-instruct** ships an **official Q4_K_M GGUF (~4.9 GB)** on
  llama.cpp/Ollama → strong RU on-device candidate for 12-16 GB devices.
  [HF yandex/YandexGPT-5-Lite-8B-instruct(-GGUF)]
- **Vikhr-7B** adds a RU-trained 40k tokenizer (~halves RU token count → faster
  on-device). ⚠️ Vikhr's "SOTA" claim **refuted** (its ACL benchmark table is
  retracted) — tokenizer facts stand, quality claims don't.
- **T-pro 2.0** (32B, Cyrillic-dense tokenizer, EAGLE specdec) = strong but
  **desktop-GPU only** (~18-20 GB at 4-bit) — fits KALI's existing desktop tier,
  not phones.
- **Tier split:** phones ≈ 7-9B class; laptop/desktop up to 14-32B.
- **Pick:** YandexGPT-5-Lite-8B (GGUF) for the on-device RU router tier; keep the
  big models on the desktop/cloud tier.

## TTS — the binding constraint 🔴 (this validates our bet)
- **Silero V5 natural RU voices = CC-BY-NC → cannot ship commercially.** Only the
  MIT `cis-base` variant is safe (lower fidelity, manual stress). Silero is fast
  on CPU (RTF 0.7). [github snakers4/silero-models]
- **Quantized F5-TTS runs on Apple Silicon via MLX** (official 4-bit/8-bit; a
  fork ships a **223 MB** quantized model "for any Apple Device"). ~4 s/sentence
  on M3 Max — but the "not real-time" claim was **split 1-2 → latency UNRESOLVED**;
  on-device quality vs cloud is **unverified**; iPhone needs MLX Swift bindings.
  → treat as a **high-value SPIKE, not a solution.** [github lucasnewman/f5-tts-mlx]
- **Licensing is a product blocker:** Silero V5 (NC) AND KALI's current F5
  checkpoint (NC) are both non-commercial. **Owning our weights solves on-device
  + license in one move** — exactly this track's thesis.
- **Biggest unverified gap (research's #1 open Q):** on-device RU TTS quality +
  latency (F5 / Kokoro / StyleTTS2 / Piper / MeloTTS) vs cloud, measured by
  MOS/UTMOS **and** RTF on a flagship **phone** (not just an M3 Max). *No surveyed
  source benchmarks Piper/Kokoro/StyleTTS2/MeloTTS on Russian at all.* → **our M0/M1
  spike + eval harness is exactly the missing measurement.**

## Runtimes — tiered, not universal
- **llama.cpp / Ollama** (GGUF) = broadest reach; Yandex + Vikhr ship official
  GGUF. **MLX** = Apple-Silicon throughput leader (short-context). [arXiv 2511.05502]
- Maps to KALI: Tauri+Python+local-GPU desktop ↔ future Flutter light client;
  MLX is the Mac/iPhone forward path, llama.cpp the cross-platform breadth.

## What this means for our F5-on-device plan
1. The **licensing crux is confirmed** → the "own our weights (F5 arch = MIT)"
   strategy is the right unlock, not just a nice-to-have.
2. We have a **concrete on-device baseline to start from**: `f5-tts-mlx` (4-bit,
   223 MB) runs on Apple Silicon **today** → M0 measures it with our harness; M1
   distills for speed.
3. The research **explicitly calls for the exact spike we planned** — RU TTS
   MOS+RTF on a phone — *which nothing in the literature has measured.* Doing it
   is both product progress and a small piece of novel evidence.
4. Router picks fall out for free: **GigaAM2 (STT, MIT)** + **YandexGPT-5-Lite-8B
   (LLM, GGUF)** for the on-device tier.
