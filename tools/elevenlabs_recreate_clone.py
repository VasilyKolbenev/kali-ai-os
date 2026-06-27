"""Recreate JARVIS voice clone in ElevenLabs with richer, higher-quality references.

Current clone uses 5 clips × 22050Hz = 20.6s total — near the IVC minimum and
downsampled from 48kHz Sound Pack source (lost upper spectrum). This script
rebuilds the clone from 10–12 clips at native 48kHz mono PCM_16, covering
short confirms / medium announcements / long tech-speak for better style range.

What it does:
  1. Reads JARVIS Sound Pack from `Jarvis Sound Pack от Jarvis Desktop/`
  2. Normalises + converts 10–12 selected clips to 48kHz mono PCM_16 WAV
  3. Writes them to `models/elevenlabs_ref_v2/` with ASCII names
  4. Deletes the previous cloned voice (if ELEVENLABS_OLD_VOICE_ID set)
  5. Creates a new IVC clone via ElevenLabs API
  6. Saves new voice_id to `%APPDATA%/KALI/elevenlabs_voice_id.txt`
  7. Prints new voice_id and a suggested Pro-tier labels/description

Usage:
    # API key required (in env or %APPDATA%/KALI/.env)
    uv run --with soundfile --with scipy --with requests --with python-dotenv \\
        python tools/elevenlabs_recreate_clone.py

Flags:
    --dry-run       Only prepare references, do not touch the API.
    --delete-old    Delete the current cloned voice before creating the new one.
    --keep-old      Keep the old voice, create a parallel clone (default).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SOUND_PACK = ROOT / "Jarvis Sound Pack от Jarvis Desktop"
OUT_DIR = ROOT / "models" / "elevenlabs_ref_v2"
APPDATA_FILE = Path(os.environ.get("APPDATA", ".")) / "KALI" / "elevenlabs_voice_id.txt"
TARGET_SR = 48_000

# Curated 12-clip selection covering short confirms / medium / long / tech tone
# Keys = stem substring (case-insensitive), values = ASCII output basename
CLIPS = [
    ("Вы создали новый элемент", "jarvis_01_created.wav"),
    ("Запрос выполнен сэр", "jarvis_02_done_sir.wav"),
    ("Загружаю сэр", "jarvis_03_loading_sir.wav"),
    ("Поздравляю сэр", "jarvis_04_congrats_sir.wav"),
    ("Начинаю диагностику системы", "jarvis_05_diagnostics.wav"),
    ("Импортирую установки, начинаю калибровку виртуальной среды",
     "jarvis_06_importing.wav"),
    ("К вашим услугам сэр", "jarvis_07_at_service.wav"),
    ("Всегда к вашим услугам сэр", "jarvis_08_always_service.wav"),
    ("Доброе утро", "jarvis_09_good_morning.wav"),
    ("Предлагаемый элемент может стать безвредной заменой палладию",
     "jarvis_10_palladium.wav"),
    ("Район Нью-Йорка", "jarvis_11_ny.wav"),
    ("Для полетов на другие планеты", "jarvis_12_planets.wav"),
]


def _find_clip(stem_hint: str) -> Path | None:
    """Find a WAV in Sound Pack, preferring exact stem match (case-insensitive).

    Falls back to substring match. Necessary because hints like "К вашим услугам сэр"
    would otherwise collide with "Всегда к вашим услугам сэр".
    """
    hint_lower = stem_hint.lower()
    for p in SOUND_PACK.glob("*.wav"):
        if p.stem.lower() == hint_lower:
            return p
    for p in SOUND_PACK.glob("*.wav"):
        if hint_lower in p.stem.lower():
            return p
    return None


def _load_48k_mono(path: Path) -> np.ndarray:
    """Load WAV, downmix to mono, resample to TARGET_SR (48kHz), normalize."""
    audio, sr = sf.read(str(path), dtype="float32")
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        audio = resample_poly(audio, TARGET_SR, sr).astype(np.float32)
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = (audio / peak * 0.95).astype(np.float32)
    return audio


def prepare_references() -> list[Path]:
    """Prepare 12 ASCII-named 48kHz mono PCM_16 WAV references in OUT_DIR."""
    if not SOUND_PACK.exists():
        raise FileNotFoundError(f"Sound Pack not found: {SOUND_PACK}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prepared: list[Path] = []
    seen_srcs: set[Path] = set()
    total_secs = 0.0

    for hint, ascii_name in CLIPS:
        src = _find_clip(hint)
        if src is None:
            logger.warning("No clip found for hint: %r", hint)
            continue
        if src in seen_srcs:
            logger.warning("Clip for hint %r already used (%s) — skipping duplicate", hint, src.name)
            continue
        seen_srcs.add(src)
        dst = OUT_DIR / ascii_name
        audio = _load_48k_mono(src)
        sf.write(str(dst), audio, TARGET_SR, subtype="PCM_16")
        dur = len(audio) / TARGET_SR
        total_secs += dur
        logger.info("  [%2d] %5.2fs  %s  \u2192  %s", len(prepared) + 1, dur,
                    src.name, ascii_name)
        prepared.append(dst)

    logger.info("")
    logger.info("Prepared %d clips, total %.1fs (target ≥30s, ideal 60–90s)",
                len(prepared), total_secs)
    if total_secs < 30:
        logger.warning("Total duration under 30s — IVC quality may still be limited")
    return prepared


def delete_old_voice(api_key: str, voice_id: str) -> None:
    """Delete a previously cloned voice by voice_id."""
    import requests
    r = requests.delete(
        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
        headers={"xi-api-key": api_key},
        timeout=30,
    )
    if r.status_code == 200:
        logger.info("Deleted old voice: %s", voice_id)
    else:
        logger.warning("Delete old voice returned [%d]: %s",
                       r.status_code, r.text[:200])


def create_clone(api_key: str, clip_paths: list[Path]) -> str:
    """Create a new Instant Voice Clone. Returns the new voice_id."""
    import requests

    files_spec = [("files", (p.name, open(p, "rb"), "audio/wav")) for p in clip_paths]
    try:
        resp = requests.post(
            "https://api.elevenlabs.io/v1/voices/add",
            headers={"xi-api-key": api_key},
            data={
                "name": "KALI_voice_v2",
                "description": (
                    "KALI assistant voice. "
                    "Calm, British, tech-sophisticated. Clone built from 12 "
                    "native-48kHz Sound Pack clips (short confirms + medium "
                    "announcements + long tech-speak)."
                ),
                "labels": '{"accent":"british","age":"middle_aged","gender":"male",'
                          '"use case":"characters_animation","description":"butler"}',
            },
            files=files_spec,
            timeout=180,
        )
    finally:
        for _, (_, fh, _) in files_spec:
            try:
                fh.close()
            except Exception:
                pass

    if resp.status_code != 200:
        raise RuntimeError(f"Clone failed [{resp.status_code}]: {resp.text[:300]}")

    voice_id = resp.json()["voice_id"]
    logger.info("Created new clone: voice_id = %s", voice_id)
    return voice_id


def save_voice_id(voice_id: str) -> None:
    """Persist new voice_id to the expected location."""
    APPDATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    APPDATA_FILE.write_text(voice_id.strip(), encoding="utf-8")
    logger.info("Saved voice_id to %s", APPDATA_FILE)


def _load_env() -> None:
    """Load API key from %APPDATA%/KALI/.env if not already in env."""
    if os.environ.get("ELEVENLABS_API_KEY"):
        return
    env_file = Path(os.environ.get("APPDATA", ".")) / "KALI" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Only prepare references, do not touch the API")
    parser.add_argument("--delete-old", action="store_true",
                        help="Delete old voice before creating the new one")
    args = parser.parse_args()

    _load_env()

    logger.info("Preparing references from Sound Pack...")
    clips = prepare_references()
    if not clips:
        logger.error("No clips prepared — aborting")
        sys.exit(1)

    if args.dry_run:
        logger.info("DRY RUN — skipping API calls. References are at %s", OUT_DIR)
        return

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        logger.error(
            "ELEVENLABS_API_KEY not set. Add to %%APPDATA%%/KALI/.env or export."
        )
        sys.exit(1)

    if args.delete_old:
        old_id = APPDATA_FILE.read_text(encoding="utf-8").strip() if APPDATA_FILE.exists() else ""
        if old_id:
            logger.info("Deleting old voice: %s", old_id)
            delete_old_voice(api_key, old_id)

    logger.info("Creating new clone from %d clips...", len(clips))
    new_voice_id = create_clone(api_key, clips)
    save_voice_id(new_voice_id)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  NEW CLONE READY")
    logger.info("=" * 60)
    logger.info("  voice_id: %s", new_voice_id)
    logger.info("  saved to: %s", APPDATA_FILE)
    logger.info("")
    logger.info("Restart KALI backend to pick up the new voice.")
    logger.info("Expected log line on restart: 'ElevenLabs ready (voices=N)'")


if __name__ == "__main__":
    main()
