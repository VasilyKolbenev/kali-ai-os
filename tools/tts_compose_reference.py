"""Compose F5-TTS reference WAV from selected JARVIS Sound Pack clips.

Takes 3-5 clean-speech clips, converts to 24kHz mono, concatenates with small
silence gaps, and saves as ``models/jarvis_ref_v2.wav`` for F5-TTS voice cloning.

Usage:
    uv run --with soundfile --with scipy python tools/tts_compose_reference.py
    # or override clips:
    uv run python tools/tts_compose_reference.py --clip "Вы создали новый элемент" --clip "Загружаю сэр"

Default selection (curated butler/tech/confirm mix):
    1. "Вы создали новый элемент"                — favorite, butler announcement
    2. "Запрос выполнен сэр"                      — short confirmation
    3. "Загружаю сэр"                             — mid-length butler
    4. "Начинаю калибровку виртуальной среды"     — tech-speak
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SOUND_PACK = ROOT / "Jarvis Sound Pack от Jarvis Desktop"
OUT_PATH = ROOT / "models" / "jarvis_ref_v2.wav"
TARGET_SR = 24_000
SILENCE_SEC = 0.25

DEFAULT_CLIPS = [
    ("Вы создали новый элемент", "Вы создали новый элемент."),
    ("Запрос выполнен сэр", "Запрос выполнен, сэр."),
    ("Загружаю сэр", "Загружаю, сэр."),
    ("Импортирую установки, начинаю калибровку виртуальной среды",
     "Импортирую установки, начинаю калибровку виртуальной среды."),
]


def load_mono_24k(wav_path: Path) -> np.ndarray:
    """Load WAV, downmix to mono, resample to TARGET_SR."""
    audio, sr = sf.read(str(wav_path), dtype="float32")
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        audio = resample_poly(audio, TARGET_SR, sr).astype(np.float32)
    return audio


def normalize_peak(audio: np.ndarray, target_peak: float = 0.85) -> np.ndarray:
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        return (audio * target_peak / peak).astype(np.float32)
    return audio


def find_clip(stem_hint: str) -> Path:
    """Find a WAV in SOUND_PACK whose stem contains ``stem_hint`` (case-insensitive)."""
    matches = [
        p for p in SOUND_PACK.glob("*.wav")
        if stem_hint.lower() in p.stem.lower()
    ]
    if not matches:
        raise FileNotFoundError(f"No clip matching: {stem_hint!r}")
    if len(matches) > 1:
        logger.warning("Multiple matches for %r, using first: %s", stem_hint, matches[0].name)
    return matches[0]


def compose(clip_hints: list[tuple[str, str]]) -> tuple[np.ndarray, str]:
    silence = np.zeros(int(TARGET_SR * SILENCE_SEC), dtype=np.float32)
    chunks: list[np.ndarray] = []
    texts: list[str] = []

    for idx, (hint, transcript) in enumerate(clip_hints):
        clip_path = find_clip(hint)
        audio = normalize_peak(load_mono_24k(clip_path))
        chunks.append(audio)
        if idx < len(clip_hints) - 1:
            chunks.append(silence)
        texts.append(transcript)
        logger.info("  [%d] %.2fs  %s", idx + 1, len(audio) / TARGET_SR, clip_path.name)

    combined = np.concatenate(chunks)
    combined = normalize_peak(combined, target_peak=0.9)
    return combined, " ".join(texts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip", action="append", help="stem substring of clip (can repeat)")
    parser.add_argument("--output", type=Path, default=OUT_PATH, help="output WAV path")
    args = parser.parse_args()

    if args.clip:
        clip_hints = [(c, c) for c in args.clip]
        logger.warning("Manual --clip mode — transcripts default to the hint. Edit ref_text manually.")
    else:
        clip_hints = DEFAULT_CLIPS

    if not SOUND_PACK.exists():
        logger.error("Sound Pack not found at %s", SOUND_PACK)
        sys.exit(1)

    logger.info("Composing reference from %d clips...", len(clip_hints))
    combined, ref_text = compose(clip_hints)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.output), combined, TARGET_SR)

    logger.info("")
    logger.info("Done: %s (%.2fs, %dHz mono)", args.output, len(combined) / TARGET_SR, TARGET_SR)
    logger.info("")
    logger.info("Suggested REFERENCE_TEXT (edit if transcripts are off):")
    logger.info('    "%s"', ref_text)


if __name__ == "__main__":
    main()
