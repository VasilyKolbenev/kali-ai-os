"""Voice-latency baseline benchmark (P0).

Measures per-stage compute latency — TTS (F5), STT (Whisper), LLM (router) —
on fixtures, no microphone. Run from the repo root with the project venv:

    .venv\\Scripts\\python.exe scripts\\measure_voice_latency.py

Prints where the milliseconds go so we optimise the right stage first
(see docs/superpowers/plans/2026-06-03-voice-latency-optimization.md).
Load times are reported but excluded from the round-trip estimate — models
are prewarmed in production.
"""

import os
import sys
import time

# Make `kernel` importable when run as `python scripts/measure_voice_latency.py`
# (the script dir, not the repo root, is sys.path[0] otherwise).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # clean UTF-8 console output on Windows
except Exception:
    pass

import asyncio

import numpy as np


def _timed(label: str, fn):
    t0 = time.perf_counter()
    out = fn()
    ms = (time.perf_counter() - t0) * 1000
    print(f"  {label:<26} {ms:9.1f} ms", flush=True)
    return out, ms


def _resample_to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return audio.astype(np.float32)
    try:
        from scipy.signal import resample_poly

        from math import gcd

        g = gcd(16000, sr)
        return resample_poly(audio, 16000 // g, sr // g).astype(np.float32)
    except Exception:
        n = int(len(audio) * 16000 / sr)
        idx = np.linspace(0, len(audio), n, endpoint=False)
        return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    sentence = "Привет, сэр. Какая сегодня погода в Москве?"
    print(f"\n=== Voice latency baseline ===\nphrase: {sentence!r}\n")

    # ── TTS (F5) ──
    print("TTS:")
    from kernel.voice import tts_router

    _, tts_load_ms = _timed("load_models", tts_router.load_models)
    (audio, sr), tts_synth_ms = _timed(
        "generate_audio", lambda: tts_router.generate_audio(sentence)
    )
    audio = np.asarray(audio, dtype=np.float32)
    audio_dur_ms = len(audio) / sr * 1000.0
    rtf = tts_synth_ms / audio_dur_ms if audio_dur_ms else 0.0
    print(
        f"  -> provider={tts_router.get_provider()} sr={sr} "
        f"audio_dur={audio_dur_ms:.0f}ms RTF={rtf:.2f}"
    )

    # ── STT (Whisper) on a short real reference clip ──
    # Transcribe a short fixture WAV, NOT the F5-synthesized audio —
    # faster-whisper on CPU went pathologically slow on the synth output.
    print("\nSTT (Whisper base):", flush=True)
    import soundfile as sf

    from kernel.voice.stt import SpeechToText

    ref_audio, ref_sr = sf.read("models/jarvis_reference.wav", dtype="float32")
    if getattr(ref_audio, "ndim", 1) > 1:
        ref_audio = ref_audio.mean(axis=1)
    audio16 = _resample_to_16k(ref_audio, ref_sr)
    stt = SpeechToText(model_size="base")
    _, stt_load_ms = _timed("load", stt.load)
    result, stt_ms = _timed("transcribe", lambda: stt.transcribe(audio16, 16000))
    print(f"  -> text={result.text!r}", flush=True)

    # ── LLM (router, non-streaming) ──
    print("\nLLM (router, full response):")
    llm_ms = None
    try:
        import yaml

        from kernel.llm_router import LLMRequest, LLMRouter
        from kernel.models import LLMConfig

        with open("config/kali.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        llm_config = LLMConfig(**cfg.get("llm", {}))
        router = LLMRouter(llm_config)
        req = LLMRequest(text=sentence, context=[], available_tools=[])
        resp, llm_ms = _timed("route", lambda: asyncio.run(router.route(req)))
        print(
            f"  -> provider={resp.provider_used} chars={len(resp.text)} "
            f"text={resp.text[:60]!r}"
        )
    except Exception as e:
        print(f"  LLM stage skipped ({type(e).__name__}: {e})")

    # ── Summary ──
    print("\n=== SUMMARY (baseline, ms — load excluded, prewarmed in prod) ===")
    print(f"  TTS synth (F5)        {tts_synth_ms:9.1f}   (RTF {rtf:.2f})")
    print(f"  STT (Whisper base)    {stt_ms:9.1f}")
    if llm_ms is not None:
        print(f"  LLM (full, cloud)     {llm_ms:9.1f}")
    print(f"  endpoint silence          700.0   (config constant)")
    print("  " + "-" * 40)
    compute = tts_synth_ms + stt_ms + (llm_ms or 0.0)
    print(f"  TTFA now (non-stream) {compute:9.1f}   (wait FULL TTS before 1st audio)")
    print(
        "  P1 (stream LLM->TTS): perceived ≈ STT + LLM_first_sentence + "
        "TTS_first_sentence  << above"
    )
    print(f"  (loads: TTS {tts_load_ms:.0f}ms, STT {stt_load_ms:.0f}ms — prewarmed)\n")


if __name__ == "__main__":
    main()
