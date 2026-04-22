"""F5-TTS A/B tuning — generate the same text with N different configs for listening.

Usage:
    uv run --with f5-tts --with soundfile python tools/tts_tune.py
    uv run python tools/tts_tune.py --text "Привет сэр. Готов помочь."

Outputs to ``out/tts_tune/`` — one WAV per config. Listen, pick the winner, update
tts_engine_f5.py with the best settings.
"""

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
OUT_DIR = ROOT / "out" / "tts_tune"


def _register_ffmpeg_dlls() -> None:
    """Add bundled FFmpeg shared DLLs to search path (torchcodec needs them).

    Must run BEFORE torch/torchaudio first import.
    """
    ffmpeg_dir = MODELS / "ffmpeg"
    if ffmpeg_dir.exists() and any(ffmpeg_dir.glob("avcodec-*.dll")):
        os.add_dll_directory(str(ffmpeg_dir))
        os.environ["PATH"] = f"{ffmpeg_dir};{os.environ.get('PATH', '')}"
        logger.info("FFmpeg DLLs registered from %s", ffmpeg_dir)
    else:
        logger.warning("FFmpeg DLLs not found in %s — F5 will likely fail to load audio", ffmpeg_dir)


_register_ffmpeg_dlls()

DEFAULT_TEST_TEXT = (
    "Приветствую, сэр. Я собрал для вас нового агента — "
    "он будет следить за курсом валют каждое утро. Готов приступить."
)

REF_V1 = MODELS / "jarvis_ref_combined.wav"   # existing baseline
REF_V1_TEXT = "Поздравляю сэр. Начинаю диагностику системы."

REF_V2 = MODELS / "jarvis_ref_v2.wav"         # composed by tts_compose_reference.py
REF_V2_TEXT = (
    "Вы создали новый элемент. Запрос выполнен, сэр. Загружаю, сэр. "
    "Импортирую установки, начинаю калибровку виртуальной среды."
)


@dataclass
class Config:
    name: str
    ref_path: Path
    ref_text: str
    speed: float = 1.0
    cfg_strength: float = 2.5
    nfe_step: int = 48
    remove_silence: bool = True
    accents: bool = False  # Apply ruaccent stress marks + punctuation normalization


# Default A/B test text containing numbers + em-dash to exercise preprocessing
DEFAULT_TEST_TEXT_FULL = (
    "Приветствую сэр — я собрал для вас нового агента. "
    "Он будет следить за курсом валют каждое утро в 8 часов. "
    "В запасе 25 минут на проверку. Готов приступить."
)


CONFIGS: list[Config] = [
    # Baseline — current prod settings from tts_engine_f5.py (pre-preprocessor)
    Config("01_baseline_v1ref", REF_V1, REF_V1_TEXT,
           speed=1.07, cfg_strength=2.5, nfe_step=48, remove_silence=True),
    # V2 reference, prod-like params
    Config("02_v2ref_prodlike", REF_V2, REF_V2_TEXT,
           speed=1.07, cfg_strength=2.5, nfe_step=48, remove_silence=True),
    # V2 ref + tuned (stronger adherence, more steps, natural pauses)
    Config("03_v2ref_tuned", REF_V2, REF_V2_TEXT,
           speed=1.0, cfg_strength=3.0, nfe_step=64, remove_silence=False),
    # V2 ref + aggressive (higher cfg — current prod winner)
    Config("04_v2ref_aggressive", REF_V2, REF_V2_TEXT,
           speed=1.0, cfg_strength=3.5, nfe_step=64, remove_silence=False),
    # V2 ref + butler-slow
    Config("05_v2ref_butler_slow", REF_V2, REF_V2_TEXT,
           speed=0.95, cfg_strength=3.0, nfe_step=64, remove_silence=False),
    # NEW: accents ON — winner params with ruaccent + punctuation + numbers preprocessing
    Config("06_aggressive_accents", REF_V2, REF_V2_TEXT,
           speed=1.0, cfg_strength=3.5, nfe_step=64, remove_silence=False,
           accents=True),
    # NEW: accents ON + butler-slow
    Config("07_butler_slow_accents", REF_V2, REF_V2_TEXT,
           speed=0.95, cfg_strength=3.0, nfe_step=64, remove_silence=False,
           accents=True),
]


def load_f5() -> object:
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading F5-TTS on %s...", device)
    from f5_tts.api import F5TTS
    ckpt = MODELS / "f5_russian_v4_winter.safetensors"
    vocab = MODELS / "f5_russian_vocab.txt"
    return F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=str(ckpt),
        vocab_file=str(vocab),
        device=device,
    )


def run_config(f5: object, cfg: Config, text: str, out_path: Path) -> float:
    if cfg.accents:
        # Apply same preprocessing as production (ruaccent + punct + numbers)
        from kernel.voice.text_preprocessor import preprocess
        text = preprocess(text)
        ref_text = preprocess(cfg.ref_text)
    else:
        ref_text = cfg.ref_text
    t0 = time.perf_counter()
    wav, sr, _ = f5.infer(  # type: ignore[attr-defined]
        ref_file=str(cfg.ref_path),
        ref_text=ref_text,
        gen_text=text,
        remove_silence=cfg.remove_silence,
        speed=cfg.speed,
        cfg_strength=cfg.cfg_strength,
        nfe_step=cfg.nfe_step,
    )
    elapsed = time.perf_counter() - t0
    audio = np.asarray(wav, dtype=np.float32)
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = audio * 0.85 / peak
    sf.write(str(out_path), audio, sr)
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_TEST_TEXT, help="text to synthesize")
    parser.add_argument("--only", help="substring filter — run only configs whose name contains this")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    configs_to_run = [c for c in CONFIGS if c.ref_path.exists()]
    skipped = [c for c in CONFIGS if not c.ref_path.exists()]
    for c in skipped:
        logger.warning("SKIP %s — reference not found: %s", c.name, c.ref_path)
    if args.only:
        configs_to_run = [c for c in configs_to_run if args.only in c.name]
    if not configs_to_run:
        logger.error("No configs to run (did you run tts_compose_reference.py first?)")
        sys.exit(1)

    f5 = load_f5()
    logger.info("Test text: %s", args.text)
    logger.info("")

    results: list[tuple[str, float, Path]] = []
    for cfg in configs_to_run:
        out = OUT_DIR / f"{cfg.name}.wav"
        logger.info("→ %s  (speed=%.2f cfg=%.1f nfe=%d silence=%s)",
                    cfg.name, cfg.speed, cfg.cfg_strength, cfg.nfe_step, cfg.remove_silence)
        elapsed = run_config(f5, cfg, args.text, out)
        logger.info("  ✓ %.2fs → %s", elapsed, out)
        results.append((cfg.name, elapsed, out))

    logger.info("")
    logger.info("Done. Listen to outputs in: %s", OUT_DIR)
    logger.info("Rank your favorites, then tell me which config to promote.")


if __name__ == "__main__":
    main()
