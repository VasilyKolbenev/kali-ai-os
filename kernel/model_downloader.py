"""Download ONNX voice models on first run.

Models are stored in the 'models/' directory relative to the executable.
Downloads from HuggingFace with progress reporting.
"""

import logging
import os
import urllib.request
from typing import Any

from kernel.runtime_paths import models_dir

logger = logging.getLogger(__name__)

MODELS_DIR = models_dir()

# NOTE: HuBERT (vec-768) and RMVPE entries removed 2026-06-11 — they were
# RVC-stack remnants (RVC retired 2026-04-22): 706 MB of dead first-run
# downloads, and the HuBERT URL 404s at every startup with a missing file.
REQUIRED_MODELS = {
    "f5_russian_accent_tune.safetensors": {
        "url": "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/F5TTS_v1_Base_accent_tune/model_last_inference.safetensors",
        "size_mb": 1350,
        "description": "F5-TTS Core Voice Model (accent-tuned: honors stress marks)",
    },
    "jarvis_ref_v2.wav": {
        "url": "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/jarvis_ref_v2.wav",
        "size_mb": 2,
        "description": "Voice Reference Audio",
    },
}

# These are trained models — shipped with installer, not downloaded
BUNDLED_MODELS: list[str] = []


def get_missing_models() -> list[dict[str, Any]]:
    """Check which downloadable support models are missing."""
    missing = []
    for name, info in REQUIRED_MODELS.items():
        path = MODELS_DIR / name
        if not path.exists():
            missing.append({"name": name, **info})
    return missing


def get_missing_bundled_models() -> list[str]:
    """Check which bundled JARVIS voice artifacts are missing."""
    return [name for name in BUNDLED_MODELS if not (MODELS_DIR / name).exists()]


def get_models_status() -> dict[str, Any]:
    """Return a detailed voice-model readiness summary."""
    downloadable_missing = get_missing_models()
    bundled_missing = get_missing_bundled_models()
    return {
        "models_dir": str(MODELS_DIR),
        "ready": not downloadable_missing and not bundled_missing,
        "missing_downloadable": [item["name"] for item in downloadable_missing],
        "missing_bundled": bundled_missing,
    }


def download_model(name: str, url: str, callback: Any = None) -> bool:
    """Download a model file with optional progress callback.

    Args:
        name: Filename to save as
        url: Download URL
        callback: Optional function(downloaded_bytes, total_bytes)

    Returns:
        True if successful
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    target = MODELS_DIR / name
    temp = target.with_suffix(".tmp")

    logger.info("Downloading %s from %s", name, url)

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "KALI/0.1.0")

        with urllib.request.urlopen(req, timeout=30) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1 MB

            with open(temp, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if callback:
                        callback(downloaded, total)

        temp.rename(target)
        logger.info("Downloaded %s (%.1f MB)", name, target.stat().st_size / 1024 / 1024)
        return True

    except Exception as e:
        logger.error("Failed to download %s: %s", name, e)
        if temp.exists():
            temp.unlink()
        return False


def ensure_models(callback: Any = None) -> bool:
    """Download all missing models. Returns True if all models are available."""
    bundled_missing = get_missing_bundled_models()
    if bundled_missing:
        logger.error(
            "Bundled voice models are missing from %s: %s",
            MODELS_DIR,
            ", ".join(bundled_missing),
        )
        return False

    missing = get_missing_models()
    if not missing:
        logger.info("All voice models present")
        return True

    total_mb = sum(m["size_mb"] for m in missing)
    logger.info("Need to download %d models (%.0f MB)", len(missing), total_mb)

    for model in missing:
        success = download_model(model["name"], model["url"], callback)
        if not success:
            return False

    return True


def models_ready() -> bool:
    """Check if all required models are downloaded."""
    status = get_models_status()
    return bool(status["ready"])
