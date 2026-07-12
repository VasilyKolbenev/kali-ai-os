"""RU TTS quality gate — «ускорение не испортило голос Джарвиса».

Scoring (pure, unit-tested): compare a candidate run against a baseline run
on ΔCER (ASR round-trip) and speaker-similarity drop → PASS / WARN / FAIL.
WARN means «в жёлтой зоне — нужен слепой A/B ушами».

Runner (GPU, manual): synthesize the FROZEN phrase set
(tests/fixtures/tts_gate_phrases.txt — never edit between experiments) with
the current env config, judge with faster-whisper, optionally score speaker
similarity with ECAPA (speechbrain; skipped honestly if not installed), save
``artifacts/tts_gate/<run-name>/run.json`` + WAVs, and print the verdict
against ``--baseline`` (default: ``baseline``).

    .venv\\Scripts\\python.exe scripts\\tts_quality_gate.py --run-name baseline
    .venv\\Scripts\\python.exe scripts\\tts_quality_gate.py --run-name nfe7 --env KALI_F5_NFE=7
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("tts_quality_gate")

PHRASES_FILE = REPO_ROOT / "tests" / "fixtures" / "tts_gate_phrases.txt"
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "tts_gate"
REFERENCE_WAV = REPO_ROOT / "models" / "jarvis_ref_v2.wav"


class Verdict(Enum):
    """Gate outcome for a candidate configuration."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class GateThresholds:
    """Quality invariants (spec 2026-07-12-f5-latency-sprint1).

    ``max_*`` are hard FAIL bounds; crossing half of a bound lands in the
    WARN zone (blind A/B required before adopting the candidate).
    """

    max_cer_delta: float = 0.005   # +0.5 п.п. CER
    max_sim_drop: float = 0.02     # ECAPA cosine drop

    @property
    def warn_cer_delta(self) -> float:
        return self.max_cer_delta / 2

    @property
    def warn_sim_drop(self) -> float:
        return self.max_sim_drop / 2


@dataclass
class GateResult:
    """Verdict + human-readable reasons (empty for a clean PASS)."""

    verdict: Verdict
    reasons: list[str] = field(default_factory=list)


def score_experiment(
    baseline: dict, candidate: dict, thresholds: GateThresholds
) -> GateResult:
    """Score a candidate run against the baseline run.

    Args:
        baseline: {"cer": float, "sim": float | None} aggregate metrics.
        candidate: same shape as baseline.
        thresholds: gate bounds.

    Returns:
        GateResult with PASS (adopt), WARN (blind A/B needed) or FAIL (reject).
    """
    reasons: list[str] = []
    verdict = Verdict.PASS
    eps = 1e-9  # boundary values must not flip verdicts on float artifacts

    cer_delta = candidate["cer"] - baseline["cer"]
    if cer_delta > thresholds.max_cer_delta + eps:
        return GateResult(
            Verdict.FAIL,
            [f"CER regression {cer_delta:+.4f} exceeds {thresholds.max_cer_delta:.4f}"],
        )
    if cer_delta > thresholds.warn_cer_delta + eps:
        verdict = Verdict.WARN
        reasons.append(f"CER delta {cer_delta:+.4f} in warn zone")

    b_sim, c_sim = baseline.get("sim"), candidate.get("sim")
    if b_sim is None or c_sim is None:
        # No speaker-similarity signal — never silently PASS on CER alone.
        verdict = Verdict.WARN
        reasons.append("SIM skipped (ECAPA/speechbrain unavailable) — ear A/B required")
    else:
        sim_drop = b_sim - c_sim
        if sim_drop > thresholds.max_sim_drop + eps:
            return GateResult(
                Verdict.FAIL,
                [f"speaker-sim drop {sim_drop:.4f} exceeds {thresholds.max_sim_drop:.4f}"],
            )
        if sim_drop > thresholds.warn_sim_drop + eps:
            verdict = Verdict.WARN
            reasons.append(f"speaker-sim drop {sim_drop:.4f} in warn zone")

    return GateResult(verdict, reasons)


# ── Text normalization + CER (no external deps) ──


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/stress marks, collapse whitespace."""
    text = text.lower().replace("+", "")
    text = re.sub(r"[^\wёа-я ]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate via Levenshtein distance on normalized text."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


# ── Runner (GPU, manual) ──


def _load_phrases() -> list[str]:
    lines = PHRASES_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def _make_judge():
    """faster-whisper judge. Beam is PINNED to 5 so the judge never degrades
    together with a candidate STT config (KALI_STT_BEAM experiments)."""
    os.environ["KALI_STT_BEAM"] = "5"
    from kernel.voice.stt import SpeechToText

    judge = SpeechToText(model_size="small")
    judge.load()
    return judge


def _make_sim_scorer():
    """ECAPA cosine similarity vs the Jarvis reference, or None if speechbrain
    is not installed (honest degradation — score_experiment turns this into WARN)."""
    try:
        import torch
        import torchaudio
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError:
        logger.warning("speechbrain not installed — SIM will be skipped (WARN)")
        return None

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(REPO_ROOT / "models" / "ecapa"),
    )

    def embed(path: Path):
        wav, sr = torchaudio.load(str(path))
        if sr != 16000:
            wav = torchaudio.transforms.Resample(sr, 16000)(wav)
        return classifier.encode_batch(wav).squeeze()

    ref_emb = embed(REFERENCE_WAV)

    def score(path: Path) -> float:
        emb = embed(path)
        return float(torch.nn.functional.cosine_similarity(ref_emb, emb, dim=-1))

    return score


def run_experiment(run_name: str, env_overrides: dict[str, str]) -> dict:
    """Synthesize the frozen set under env_overrides; return aggregate metrics."""
    import numpy as np
    import soundfile as sf

    os.environ.update(env_overrides)
    from kernel.voice import tts_router

    out_dir = ARTIFACTS_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    tts_router.load_models()
    # Warmup: first synth carries CUDA compile cost — keep it out of timings.
    tts_router.generate_audio("Прогрев, сэр.")

    judge = _make_judge()
    sim_scorer = _make_sim_scorer()

    phrases = _load_phrases()
    per_phrase: list[dict] = []
    import torch

    for idx, phrase in enumerate(phrases):
        # Deterministic noise per phrase: the fast path dropped api.infer's
        # per-call seed_everything, so without this the flow-matching y0 noise
        # differs run-to-run and CER deltas between configs drown in sampling
        # variance (observed ±2+ п.п. on identical configs, 2026-07-12).
        torch.manual_seed(42 + idx)
        t0 = time.perf_counter()
        audio, sr = tts_router.generate_audio(phrase)
        synth_ms = (time.perf_counter() - t0) * 1000
        audio = np.asarray(audio, dtype=np.float32)
        wav_path = out_dir / f"{idx:02d}.wav"
        sf.write(str(wav_path), audio, sr)

        audio16 = audio if sr == 16000 else _resample(audio, sr)
        stt = judge.transcribe(audio16, 16000)
        phrase_cer = cer(phrase, stt.text)
        sim = sim_scorer(wav_path) if sim_scorer else None
        per_phrase.append(
            {"phrase": phrase, "cer": phrase_cer, "sim": sim,
             "synth_ms": synth_ms, "audio_ms": len(audio) / sr * 1000}
        )
        logger.info("[%02d] cer=%.4f sim=%s synth=%.0fms", idx, phrase_cer, sim, synth_ms)

    sims = [p["sim"] for p in per_phrase if p["sim"] is not None]
    metrics = {
        "run_name": run_name,
        "env": env_overrides,
        "cer": sum(p["cer"] for p in per_phrase) / len(per_phrase),
        "sim": (sum(sims) / len(sims)) if sims else None,
        "synth_ms_median": sorted(p["synth_ms"] for p in per_phrase)[len(per_phrase) // 2],
        "phrases": per_phrase,
    }
    (out_dir / "run.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return metrics


def _resample(audio, sr: int):
    from scipy.signal import resample_poly
    from math import gcd

    g = gcd(16000, sr)
    return resample_poly(audio, 16000 // g, sr // g).astype("float32")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — cosmetic console tweak only
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VAL")
    parser.add_argument("--baseline", default="baseline")
    args = parser.parse_args()

    overrides = dict(kv.split("=", 1) for kv in args.env)
    metrics = run_experiment(args.run_name, overrides)

    baseline_path = ARTIFACTS_DIR / args.baseline / "run.json"
    if args.run_name == args.baseline or not baseline_path.exists():
        print(f"\n[{args.run_name}] cer={metrics['cer']:.4f} sim={metrics['sim']} "
              f"synth_median={metrics['synth_ms_median']:.0f}ms (no comparison run)")
        return

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    result = score_experiment(baseline, metrics, GateThresholds())
    print(f"\n=== GATE: {args.run_name} vs {args.baseline} ===")
    print(f"  CER  {baseline['cer']:.4f} → {metrics['cer']:.4f}")
    print(f"  SIM  {baseline['sim']} → {metrics['sim']}")
    print(f"  synth median {baseline['synth_ms_median']:.0f} → {metrics['synth_ms_median']:.0f} ms")
    print(f"  VERDICT: {result.verdict.value.upper()}")
    for reason in result.reasons:
        print(f"   - {reason}")


if __name__ == "__main__":
    main()
