"""Wire the on-device TTS eval harness to KALI's real engines (M0 baseline).

Synthesis = F5-TTS Russian (``kernel.voice.tts_engine_f5``); transcription =
faster-whisper (``kernel.voice.stt.SpeechToText``) — the exact STT KALI ships,
including its domain ``initial_prompt`` and VAD. Produces the M0 baseline:
WER/CER (intelligibility via STT round-trip) + RTF (speed) per category.

Device is *ambient* — whatever torch sees. For the on-device RTF gate, launch
with CUDA hidden so F5 + Whisper both run on CPU::

    CUDA_VISIBLE_DEVICES=-1 .venv/Scripts/python.exe research/on-device-tts/run_m0.py --label cpu

GPU baseline + saved audio for blind listening::

    .venv/Scripts/python.exe research/on-device-tts/run_m0.py --label gpu --save-audio

Reports land in ``research/on-device-tts/runs/<label>/`` (results.json +
report.md, plus audio/<id>.wav when ``--save-audio``).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
# HERE: lets ``run_eval`` resolve its sibling ``from metrics import ...``.
# REPO_ROOT: lets us ``import kernel.voice.*``.
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

# Force HF fully offline against the project cache before any kernel import.
# Every model the eval needs is already present (F5 ckpt is local; vocos +
# faster-whisper snapshots live under .hf_cache), so skip HF Hub's online
# etag/HEAD checks — one of those hangs on a slow CDN connection (a 32-min
# stall observed without this). Mirrors what production entry.py does.
os.environ.setdefault("HF_HOME", str(REPO_ROOT / ".hf_cache"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from run_eval import evaluate, load_eval_set, summarize, write_report  # noqa: E402

logger = logging.getLogger("m0")

STT_SR = 16000  # faster-whisper expects 16 kHz mono float32; F5 emits 24 kHz.


def _build_synth(
    save_dir: Path | None, ids: list[str]
) -> Callable[[str], tuple[Any, float, float]]:
    """Build a synth callable over KALI's F5 engine.

    Times the full text→audio path (preprocessing + stress + chunked F5), so RTF
    reflects what a user actually waits for. Returns ``((audio, sr), synth_s,
    audio_s)``; raises on silent output so a failed utterance is recorded as an
    error rather than poisoning the WER/RTF aggregates.

    Args:
        save_dir: If set, write each utterance to ``<save_dir>/<id>.wav``.
        ids: Eval-set ids in iteration order (for audio filenames).

    Returns:
        A synth callable matching ``run_eval.SynthFn``.
    """
    from kernel.voice import tts_engine_f5

    tts_engine_f5.load_models()
    # Warm up once before any timed item: the first synth pays one-off costs
    # (CUDA kernel compile / cuDNN autotune / lazy init) that otherwise show up
    # as a ~30x RTF outlier and poison the mean. RTF must reflect steady state.
    try:
        tts_engine_f5.generate_audio("Система готова к работе.")
        logger.info("synth warmup done")
    except Exception:
        logger.warning("synth warmup failed (non-fatal)", exc_info=True)
    state = {"i": 0}

    def synth(text: str) -> tuple[Any, float, float]:
        idx = state["i"]
        state["i"] += 1
        t0 = time.perf_counter()
        audio, sr = tts_engine_f5.generate_audio(text)
        synth_s = time.perf_counter() - t0
        audio = np.asarray(audio, dtype=np.float32)
        if audio.size == 0 or not np.any(audio):
            raise RuntimeError("F5 produced empty/silent audio")
        if save_dir is not None:
            import soundfile as sf

            name = ids[idx] if idx < len(ids) else f"{idx:03d}"
            sf.write(str(save_dir / f"{name}.wav"), audio, sr)
        return (audio, sr), synth_s, len(audio) / sr

    return synth


def _build_stt() -> Callable[[Any], str]:
    """Build an STT callable over KALI's faster-whisper engine.

    Resamples F5's 24 kHz output down to Whisper's 16 kHz before transcribing.

    Returns:
        An STT callable matching ``run_eval.SttFn``.

    Raises:
        RuntimeError: If the Whisper model fails to load.
    """
    from kernel.voice.stt import SpeechToText

    engine = SpeechToText()  # inherits KALI_STT_MODEL if set, else "base"
    engine.load()
    if not engine.is_loaded:
        raise RuntimeError("Whisper failed to load — cannot run STT round-trip")

    def stt(audio_ref: Any) -> str:
        audio, sr = audio_ref
        if sr != STT_SR:
            import librosa

            audio = librosa.resample(
                np.asarray(audio, dtype=np.float32), orig_sr=sr, target_sr=STT_SR
            )
        return engine.transcribe(audio, sample_rate=STT_SR).text

    return stt


def run(label: str, limit: int, save_audio: bool) -> dict[str, Any]:
    """Run the eval against the real engines and write the report.

    Args:
        label: Subdir name under ``runs/`` (e.g. ``gpu``, ``cpu``, ``smoke``).
        limit: If > 0, only the first N eval items (smoke testing).
        save_audio: Persist per-utterance WAVs for blind listening.

    Returns:
        The summary dict (also written to ``runs/<label>/results.json``).
    """
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    items = load_eval_set()
    if limit > 0:
        items = items[:limit]

    out_dir = HERE / "runs" / label
    audio_dir = out_dir / "audio" if save_audio else None
    if audio_dir is not None:
        audio_dir.mkdir(parents=True, exist_ok=True)

    logger.info("M0 eval — label=%s device=%s items=%d save_audio=%s", label, device, len(items), save_audio)
    synth = _build_synth(audio_dir, [it["id"] for it in items])
    stt = _build_stt()

    t0 = time.perf_counter()
    results = evaluate(items, synth, stt)
    summary = summarize(results)
    wall_s = time.perf_counter() - t0

    summary["meta"] = {
        "label": label,
        "device": device,
        "stt_model": os.environ.get("KALI_STT_MODEL", "base"),
        "n_items": len(items),
        "wall_s": round(wall_s, 1),
    }
    write_report(results, summary, out_dir)

    ov = summary.get("overall", {})
    logger.info(
        "DONE label=%s device=%s WER=%.3f CER=%.3f RTF=%.3f errors=%d wall=%.0fs",
        label, device, ov.get("wer", float("nan")), ov.get("cer", float("nan")),
        ov.get("rtf", float("nan")), len(summary.get("errors", [])), wall_s,
    )
    return summary


def main() -> None:
    """CLI entry point: parse args and run one labelled eval pass."""
    ap = argparse.ArgumentParser(description="M0 on-device TTS baseline runner")
    ap.add_argument("--label", required=True, help="runs/<label> output subdir")
    ap.add_argument("--limit", type=int, default=0, help="only first N items (smoke)")
    ap.add_argument("--save-audio", action="store_true", help="save per-utterance WAVs")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run(args.label, args.limit, args.save_audio)


if __name__ == "__main__":
    main()
