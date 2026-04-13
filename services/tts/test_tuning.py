"""Tuning variants for jarvis_v2 voice — EQ, index, pitch.

Generates multiple variants of the same phrase with different settings.

Usage:
    cd C:/Users/User/Desktop/Jarvis
    uv run python services/tts/test_tuning.py
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.tts.rvc_onnx import RVCEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "models"
OUTPUT_DIR = Path(__file__).parent.parent.parent
MODEL_SR = 40000


def apply_eq(audio: np.ndarray, sr: int, profile: str) -> np.ndarray:
    """Apply EQ filtering via FFT.

    Profiles:
    - jarvis_v1: low=10%, mid=89%, high=1% (original tuning)
    - warm: boost lows, slight mid cut, roll off highs (warmer/deeper)
    - bright: slight low cut, flat mids, slight high boost
    - deep: boost low-mids, cut highs (deeper voice)
    """
    profiles = {
        "jarvis_v1": {"low": 0.10, "mid": 0.89, "high": 0.01},
        "warm": {"low": 0.30, "mid": 0.80, "high": 0.05},
        "bright": {"low": 0.15, "mid": 0.85, "high": 0.20},
        "deep": {"low": 0.40, "mid": 0.75, "high": 0.02},
        "balanced": {"low": 0.20, "mid": 0.85, "high": 0.10},
    }

    p = profiles[profile]

    # FFT
    spectrum = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)

    # Apply gains per band
    gains = np.ones_like(freqs)

    # Low band: 0 - 300 Hz
    low_mask = freqs < 300
    gains[low_mask] = p["low"]

    # Mid band: 300 - 4000 Hz
    mid_mask = (freqs >= 300) & (freqs < 4000)
    gains[mid_mask] = p["mid"]

    # High band: 4000+ Hz
    high_mask = freqs >= 4000
    gains[high_mask] = p["high"]

    # Smooth transitions between bands (50 Hz crossfade)
    for edge, width in [(300, 50), (4000, 200)]:
        transition = (freqs >= edge - width) & (freqs < edge + width)
        if np.any(transition):
            t_freqs = freqs[transition]
            alpha = (t_freqs - (edge - width)) / (2 * width)
            below_gain = gains[freqs < edge - width][-1] if np.any(freqs < edge - width) else 1.0
            above_gain = gains[freqs >= edge + width][0] if np.any(freqs >= edge + width) else 1.0
            gains[transition] = below_gain * (1 - alpha) + above_gain * alpha

    spectrum *= gains
    result = np.fft.irfft(spectrum, n=len(audio))
    return result.astype(np.float32)


def normalize(audio: np.ndarray, target_peak: float = 0.7) -> np.ndarray:
    """Normalize audio to target peak level."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        return (audio * target_peak / peak).astype(np.float32)
    return audio


def generate_silero_audio(text: str) -> tuple[np.ndarray, int]:
    """Generate audio with Silero TTS v4."""
    import torch

    torch.hub._validate_not_a_forked_repo = lambda a, b, c: True
    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker="v4_ru",
        trust_repo=True,
    )
    sr = 48000
    audio = model.apply_tts(text=text, speaker="eugene", sample_rate=sr)
    return audio.numpy(), sr


def main() -> None:
    """Generate tuning variants."""
    text = "Добрый вечер, сэр. Все системы работают в штатном режиме."

    logger.info("Generating Silero TTS audio...")
    tts_audio, tts_sr = generate_silero_audio(text)

    # Define tuning variants
    variants = [
        # (name, index_influence, pitch_shift, eq_profile)
        ("v2_raw", 0.8, 0, None),
        ("v2_eq_jarvis", 0.8, 0, "jarvis_v1"),
        ("v2_eq_warm", 0.8, 0, "warm"),
        ("v2_eq_deep", 0.8, 0, "deep"),
        ("v2_eq_balanced", 0.8, 0, "balanced"),
        ("v2_idx06", 0.6, 0, "jarvis_v1"),
        ("v2_idx09", 0.9, 0, "jarvis_v1"),
        ("v2_pitch_m1", 0.8, -1, "jarvis_v1"),
        ("v2_pitch_p1", 0.8, 1, "jarvis_v1"),
    ]

    for name, idx_influence, pitch_shift, eq_profile in variants:
        logger.info("=" * 50)
        logger.info("Variant: %s (idx=%.1f, pitch=%+d, eq=%s)",
                     name, idx_influence, pitch_shift, eq_profile or "none")

        engine = RVCEngine(
            model_path=str(MODELS_DIR / "jarvis_v2.onnx"),
            index_path=str(MODELS_DIR / "jarvis_v2.index"),
            hubert_path=str(MODELS_DIR / "vec-768-layer-12.onnx"),
            rmvpe_path=str(MODELS_DIR / "rmvpe.onnx"),
            index_influence=idx_influence,
            model_sr=MODEL_SR,
        )

        t0 = time.perf_counter()
        result = engine.convert(tts_audio, sr=tts_sr, pitch_shift=pitch_shift)
        t_convert = time.perf_counter() - t0

        # Apply EQ if specified
        if eq_profile:
            result = apply_eq(result, MODEL_SR, eq_profile)

        result = normalize(result)

        output_file = OUTPUT_DIR / f"test_tune_{name}.wav"
        sf.write(str(output_file), result, MODEL_SR)

        duration = len(result) / MODEL_SR
        logger.info("%s: %.2fs convert, %.1fs audio → %s",
                     name, t_convert, duration, output_file.name)

    logger.info("=" * 50)
    logger.info("Tuning complete! Files in project root:")
    logger.info("")
    logger.info("  EQ variants (compare these first):")
    logger.info("    test_tune_v2_raw.wav        — без EQ (baseline)")
    logger.info("    test_tune_v2_eq_jarvis.wav   — EQ jarvis (low=10%% mid=89%% high=1%%)")
    logger.info("    test_tune_v2_eq_warm.wav     — EQ warm (больше low, меньше high)")
    logger.info("    test_tune_v2_eq_deep.wav     — EQ deep (голубое low-mid)")
    logger.info("    test_tune_v2_eq_balanced.wav — EQ balanced (ровный)")
    logger.info("")
    logger.info("  Index influence (с jarvis EQ):")
    logger.info("    test_tune_v2_idx06.wav — index=0.6 (больше оригинала)")
    logger.info("    test_tune_v2_idx09.wav — index=0.9 (больше JARVIS)")
    logger.info("")
    logger.info("  Pitch shift (с jarvis EQ):")
    logger.info("    test_tune_v2_pitch_m1.wav — -1 semitone (ниже)")
    logger.info("    test_tune_v2_pitch_p1.wav — +1 semitone (выше)")


if __name__ == "__main__":
    main()
