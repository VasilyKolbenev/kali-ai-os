"""Voice-latency baseline benchmark (P0, honest edition 2026-07-12).

Measures per-stage compute latency — TTS (F5, WARM medians after a discarded
warmup synth), STT (Whisper, model from config), LLM (router) — on fixtures,
no microphone. Run from the repo root with the project venv:

    .venv\\Scripts\\python.exe scripts\\measure_voice_latency.py [--skip-stt]

The 2026-06 edition measured the COLD first synth (CUDA warmup inflated F5
~4x) and hardcoded silence=700ms / STT "base" — this edition reports warm
medians, reads the real constants, and can skip the STT stage (known to hang
pathologically on some CPU paths — 2026-07-12).
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import asyncio

import numpy as np

SHORT = "Да, сэр."
MED = "Привет, сэр. Какая сегодня погода в Москве?"
LONG = (
    "Конечно, сэр. Сейчас проверю прогноз погоды и расскажу, "
    "стоит ли брать зонт с собой сегодня вечером."
)


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
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(16000, sr)
        return resample_poly(audio, 16000 // g, sr // g).astype(np.float32)
    except Exception:
        n = int(len(audio) * 16000 / sr)
        idx = np.linspace(0, len(audio), n, endpoint=False)
        return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def _measure_tts() -> dict[str, float]:
    """Warm F5 medians: load → warmup (discard) → 3xshort / 3xmed / 2xlong."""
    from kernel.voice import tts_router

    print("TTS (F5, warm medians):")
    _, load_ms = _timed("load_models", tts_router.load_models)

    def synth(text: str) -> tuple[float, float]:
        t0 = time.perf_counter()
        audio, sr = tts_router.generate_audio(text)
        ms = (time.perf_counter() - t0) * 1000
        audio = np.asarray(audio, dtype=np.float32)
        return ms, len(audio) / sr * 1000.0

    warm_ms, _ = synth(SHORT)
    print(f"  warmup (discarded)         {warm_ms:9.1f} ms")

    out: dict[str, float] = {"load_ms": load_ms}
    for label, text, n in (("short", SHORT, 3), ("med", MED, 3), ("long", LONG, 2)):
        runs = [synth(text) for _ in range(n)]
        med_ms = statistics.median(ms for ms, _ in runs)
        audio_ms = runs[0][1]
        rtf = med_ms / audio_ms if audio_ms else 0.0
        out[f"{label}_ms"] = med_ms
        out[f"{label}_rtf"] = rtf
        print(f"  {label:<8} median x{n}        {med_ms:9.1f} ms  (audio {audio_ms:.0f} ms, RTF {rtf:.2f})")
    return out


def _measure_stt() -> float | None:
    """Transcribe the reference clip with the CONFIGURED model (not 'base')."""
    import faulthandler

    import soundfile as sf
    import yaml

    from kernel.voice.stt import SpeechToText

    with open("config/kali.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    model_size = (cfg.get("voice") or {}).get("stt_model", "small")
    print(f"\nSTT (Whisper {model_size}):", flush=True)

    # Known 2026-07-12 hazard: STT load hung pathologically on a CPU path.
    # Dump a traceback if any single step exceeds 120s so the hang is visible.
    faulthandler.dump_traceback_later(120, exit=False)
    try:
        ref_audio, ref_sr = sf.read("models/jarvis_reference.wav", dtype="float32")
        if getattr(ref_audio, "ndim", 1) > 1:
            ref_audio = ref_audio.mean(axis=1)
        audio16 = _resample_to_16k(ref_audio, ref_sr)
        stt = SpeechToText(model_size=model_size)
        _, load_ms = _timed("load", stt.load)
        result, stt_ms = _timed("transcribe", lambda: stt.transcribe(audio16, 16000))
        print(f"  -> text={result.text!r}", flush=True)
        return stt_ms
    finally:
        faulthandler.cancel_dump_traceback_later()


def _measure_llm() -> float | None:
    print("\nLLM (router, full response):")
    try:
        import yaml

        from kernel.llm_router import LLMRequest, LLMRouter
        from kernel.models import LLMConfig

        with open("config/kali.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        router = LLMRouter(LLMConfig(**cfg.get("llm", {})))
        req = LLMRequest(text=MED, context=[], available_tools=[])
        resp, llm_ms = _timed("route", lambda: asyncio.run(router.route(req)))
        print(f"  -> provider={resp.provider_used} chars={len(resp.text)}")
        return llm_ms
    except Exception as e:
        print(f"  LLM stage skipped ({type(e).__name__}: {e})")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-stt", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    silence_ms = int(os.environ.get("KALI_SILENCE_MS", "900"))
    print(f"\n=== Voice latency baseline (warm) ===")
    print(f"silence window: {silence_ms} ms (KALI_SILENCE_MS)\n")

    tts = _measure_tts()
    stt_ms = None if args.skip_stt else _measure_stt()
    llm_ms = None if args.skip_llm else _measure_llm()

    print("\n=== SUMMARY (ms; loads excluded — prewarmed in prod) ===")
    print(f"  endpoint silence      {silence_ms:9.1f}   (KALI_SILENCE_MS)")
    if stt_ms is not None:
        print(f"  STT                   {stt_ms:9.1f}")
    if llm_ms is not None:
        print(f"  LLM (full, cloud)     {llm_ms:9.1f}")
    print(f"  TTS first chunk~short {tts['short_ms']:9.1f}   (RTF {tts['short_rtf']:.2f})")
    print(f"  TTS med sentence      {tts['med_ms']:9.1f}   (RTF {tts['med_rtf']:.2f})")
    print("  " + "-" * 44)
    known = silence_ms + tts["short_ms"] + (stt_ms or 0.0) + (llm_ms or 0.0)
    print(
        f"  TTFA estimate         {known:9.1f}   "
        f"(silence + STT + LLM-full + TTS-first; streaming LLM shrinks the LLM term "
        f"to first-sentence time)"
    )


if __name__ == "__main__":
    main()
