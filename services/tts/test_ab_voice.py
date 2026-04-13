"""A/B test: compare jarvis_v1, jarvis_v2, jarvis_v2_best voice models.

Generates the same phrase through Silero TTS + each RVC ONNX model,
saves WAV files for listening comparison.

Usage:
    cd C:/Users/User/Desktop/Jarvis
    uv run python services/tts/test_ab_voice.py
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

MODELS = {
    "jarvis_v1": {
        "model": MODELS_DIR / "jarvis_v1.onnx",
        "index": MODELS_DIR / "jarvis_v1.index",
    },
    "jarvis_v2": {
        "model": MODELS_DIR / "jarvis_v2.onnx",
        "index": MODELS_DIR / "jarvis_v2.index",
    },
    "jarvis_v2_best": {
        "model": MODELS_DIR / "jarvis_v2_best.onnx",
        "index": MODELS_DIR / "jarvis_v2.index",
    },
}

MODEL_SR = 40000  # All models trained at 40kHz


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
    """Run A/B test across all models."""
    text = "Добрый вечер, сэр. Все системы работают в штатном режиме."

    logger.info("Generating Silero TTS audio...")
    tts_audio, tts_sr = generate_silero_audio(text)
    sf.write(str(OUTPUT_DIR / "test_ab_silero_raw.wav"), tts_audio, tts_sr)
    logger.info(
        "Silero raw: %.1fs at %dHz", len(tts_audio) / tts_sr, tts_sr,
    )

    for name, paths in MODELS.items():
        model_path = paths["model"]
        index_path = paths["index"]

        if not model_path.exists():
            logger.warning("Skipping %s - model not found", name)
            continue

        logger.info("=" * 60)
        logger.info("Testing model: %s", name)

        engine = RVCEngine(
            model_path=str(model_path),
            index_path=str(index_path) if index_path.exists() else None,
            hubert_path=str(MODELS_DIR / "vec-768-layer-12.onnx"),
            rmvpe_path=str(MODELS_DIR / "rmvpe.onnx"),
            index_influence=0.8,
            model_sr=MODEL_SR,
        )

        t0 = time.perf_counter()
        engine.load()
        logger.info("Model loaded in %.2fs", time.perf_counter() - t0)

        t1 = time.perf_counter()
        result = engine.convert(tts_audio, sr=tts_sr)
        t_convert = time.perf_counter() - t1

        # Normalize
        peak = np.max(np.abs(result))
        if peak > 0:
            result = (result * 0.7 / peak).astype(np.float32)

        output_file = OUTPUT_DIR / f"test_ab_{name}.wav"
        sf.write(str(output_file), result, MODEL_SR)

        duration = len(result) / MODEL_SR
        logger.info(
            "%s: convert=%.2fs, output=%.1fs, file=%s",
            name, t_convert, duration, output_file.name,
        )

    logger.info("=" * 60)
    logger.info("A/B test complete! Compare files in project root:")
    logger.info("  test_ab_silero_raw.wav     - Silero raw (no RVC)")
    logger.info("  test_ab_jarvis_v1.wav      - RVC v1")
    logger.info("  test_ab_jarvis_v2.wav      - RVC v2 epoch 400")
    logger.info("  test_ab_jarvis_v2_best.wav - RVC v2 epoch 50 (best loss)")


if __name__ == "__main__":
    main()
