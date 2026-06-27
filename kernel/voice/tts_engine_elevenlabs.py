"""ElevenLabs TTS engine — cloud voice cloning + synthesis.

Setup (one-time, when ELEVENLABS_API_KEY is set):
1. Upload JARVIS reference clips → creates custom voice
2. Save voice_id to %APPDATA%/KALI/elevenlabs_voice_id.txt
3. Future calls use saved voice_id for synthesis

Requires:
- ElevenLabs Starter plan or higher ($5/mo) for voice cloning
- API key with permissions: voices_read, voices_write, create_instant_voice_clone, text_to_speech
"""

from __future__ import annotations

import logging
import os
import time
import re
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

JARVIS_REFERENCE_CLIPS = [
    "Поздравляю сэр.wav",
    "Начинаю диагностику системы (второй).wav",
    "Район Нью-Йорка, Манхэттэн и окрестности.wav",
    "Предлагаемый элемент может стать безвредной заменой палладию.wav",
    "Вы создали новый элемент.wav",
]

# Fallback preset voices (work on free tier, no cloning needed)
# User can override via ELEVENLABS_VOICE_ID env or Settings
JARVIS_PRESET_VOICES = {
    "daniel": "onwK4e9ZLuTAKqWW03F9",   # British male, calm butler (best JARVIS-like)
    "george": "JBFqnCBsd6RMkjVDRZzb",   # British male, deep authoritative
    "adam": "pNInz6obpgDQGcFmaJgB",     # American male, deep narrator
}
DEFAULT_PRESET = "daniel"


def _appdata_dir() -> Path:
    """Return writable AppData directory."""
    import sys
    if hasattr(sys, "_MEIPASS"):
        return Path(os.environ.get("APPDATA", "")) / "KALI"
    return Path(__file__).parent.parent.parent / "data"


def _sound_pack_dir() -> Path:
    """Find the JARVIS Sound Pack directory."""
    import sys
    if hasattr(sys, "_MEIPASS"):
        exe_dir = Path(sys.executable).parent
        for c in [exe_dir / "sound_pack", _appdata_dir() / "sound_pack"]:
            if c.exists():
                return c
    return Path(__file__).parent.parent.parent / "Jarvis Sound Pack от Jarvis Desktop"


def _voice_id_file() -> Path:
    """File storing the cloned voice_id after first upload."""
    d = _appdata_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "elevenlabs_voice_id.txt"


def _get_saved_voice_id() -> str | None:
    """Load previously cloned voice_id."""
    f = _voice_id_file()
    if f.exists():
        return f.read_text().strip() or None
    return None


def _save_voice_id(voice_id: str) -> None:
    """Persist voice_id for future sessions."""
    _voice_id_file().write_text(voice_id.strip())


def _prepare_reference_clips(sound_dir: Path) -> list[Path]:
    """Get ElevenLabs-ready reference clips. Uses bundled pre-converted ones first.

    ElevenLabs IVC rejects files with Cyrillic names in multipart upload
    and some exotic WAV variants. Bundled installer ships pre-converted
    ASCII-named PCM_16 mono clips. Falls back to on-the-fly conversion
    from Sound Pack for dev mode.
    """
    import soundfile as sf
    import numpy as np

    # Target dir — inside app's models dir
    import sys
    if hasattr(sys, "_MEIPASS"):
        exe_dir = Path(sys.executable).parent
        dst_dir = exe_dir / "models" / "elevenlabs_ref"
    else:
        dst_dir = Path(__file__).parent.parent.parent / "models" / "elevenlabs_ref"

    # Fast path: bundled clips already present
    if dst_dir.exists():
        bundled = sorted(dst_dir.glob("jarvis_*.wav"))
        if bundled:
            return bundled

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Russian name → ASCII name mapping
    mapping = {
        "Поздравляю сэр.wav": "jarvis_01_congrats.wav",
        "Начинаю диагностику системы (второй).wav": "jarvis_02_diagnostic.wav",
        "Район Нью-Йорка, Манхэттэн и окрестности.wav": "jarvis_03_ny.wav",
        "Предлагаемый элемент может стать безвредной заменой палладию.wav": "jarvis_04_element.wav",
        "Вы создали новый элемент.wav": "jarvis_05_created.wav",
    }

    prepared: list[Path] = []
    for ru_name, ascii_name in mapping.items():
        src = sound_dir / ru_name
        if not src.exists():
            continue
        dst = dst_dir / ascii_name
        if dst.exists() and dst.stat().st_size > 1024:
            prepared.append(dst)
            continue
        try:
            audio, sr = sf.read(str(src))
            if audio.ndim > 1:
                audio = audio[:, 0]  # mono
            audio = audio.astype(np.float32)
            peak = float(np.max(np.abs(audio)))
            if peak > 0:
                audio = audio / peak * 0.9
            sf.write(str(dst), audio, int(sr), subtype="PCM_16")
            prepared.append(dst)
        except Exception as exc:
            logger.warning("Failed to re-encode %s: %s", ru_name, exc)

    return prepared


class ElevenLabsEngine:
    """TTS engine using ElevenLabs cloud with custom JARVIS voice clone."""

    def __init__(self, api_key: str | None = None, voice_id: str | None = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id or _get_saved_voice_id()
        self._client: Any = None

    def _client_lazy(self) -> Any:
        """Lazy-create ElevenLabs client."""
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("ELEVENLABS_API_KEY not set")
            from elevenlabs.client import ElevenLabs
            self._client = ElevenLabs(api_key=self.api_key)
        return self._client

    def ensure_voice_clone(self) -> str:
        """Get voice_id — try cached clone, else clone JARVIS, else fallback to preset.

        Returns:
            voice_id string (cloned or preset).
        """
        if self.voice_id:
            return self.voice_id

        # Env override: user can set ELEVENLABS_VOICE_ID directly
        env_override = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
        if env_override:
            self.voice_id = env_override
            _save_voice_id(env_override)
            logger.info("Using voice_id from env: %s", env_override)
            return env_override

        # Try to clone JARVIS from Sound Pack (requires paid plan).
        # Convert Cyrillic-named WAVs to ASCII + PCM_16 mono (ElevenLabs rejects
        # some exotic formats or multipart payloads with non-ASCII filenames).
        sound_dir = _sound_pack_dir()
        prepared = _prepare_reference_clips(sound_dir)

        if prepared:
            logger.info("Attempting JARVIS voice clone (%d clips)...", len(prepared))
            try:
                # Use raw HTTP to avoid elevenlabs-SDK multipart edge cases
                import requests
                with_files = [
                    ("files", (f.name, open(f, "rb"), "audio/wav")) for f in prepared
                ]
                try:
                    resp = requests.post(
                        "https://api.elevenlabs.io/v1/voices/add",
                        headers={"xi-api-key": self.api_key},
                        data={
                            "name": "KALI_voice",
                            "description": "KALI assistant voice",
                        },
                        files=with_files,
                        timeout=120,
                    )
                finally:
                    for _, (_, fh, _) in with_files:
                        try: fh.close()
                        except Exception: pass

                if resp.status_code == 200:
                    self.voice_id = resp.json()["voice_id"]
                    _save_voice_id(self.voice_id)
                    logger.info("JARVIS cloned: %s", self.voice_id)
                    return self.voice_id
                # Not 200 → analyze and fall back
                err_text = resp.text.lower()
                if "paid_plan" in err_text or "subscription" in err_text or "payment" in err_text:
                    logger.warning("Voice cloning requires paid ElevenLabs plan — using preset '%s'", DEFAULT_PRESET)
                else:
                    logger.warning("Voice clone failed [%d]: %s — using preset '%s'", resp.status_code, resp.text[:200], DEFAULT_PRESET)
            except Exception as exc:
                logger.warning("Voice clone exception: %s — using preset '%s'", exc, DEFAULT_PRESET)

        # Fallback: preset voice (works on free tier)
        preset_name = os.environ.get("ELEVENLABS_PRESET", DEFAULT_PRESET)
        preset_id = JARVIS_PRESET_VOICES.get(preset_name, JARVIS_PRESET_VOICES[DEFAULT_PRESET])
        self.voice_id = preset_id
        _save_voice_id(preset_id)
        logger.info("Using preset voice '%s' (id=%s)", preset_name, preset_id)
        return preset_id

    def synthesize(self, text: str, language: str | None = None) -> tuple[np.ndarray, int]:
        """Generate JARVIS voice audio via ElevenLabs cloud.

        Args:
            text: Input text (any language supported by ElevenLabs multilingual model).
            language: Ignored — ElevenLabs auto-detects.

        Returns:
            Tuple of (audio float32 mono, sample_rate 44100).
        """
        del language
        voice_id = self.ensure_voice_clone()
        client = self._client_lazy()

        t0 = time.perf_counter()
        audio_stream = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",  # best quality for ru+en mix
            output_format="mp3_44100_128",
        )

        # Collect all chunks
        audio_bytes = b"".join(audio_stream)

        # Decode MP3 → numpy float32
        import io
        import soundfile as sf
        try:
            audio, sr = sf.read(io.BytesIO(audio_bytes))
        except Exception:
            # Fallback: save to temp file and read
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                audio, sr = sf.read(tmp_path)
            finally:
                os.unlink(tmp_path)

        if audio.ndim > 1:
            audio = audio[:, 0]
        audio = audio.astype(np.float32)

        logger.info(
            "ElevenLabs TTS: %d chars → %.1fs audio in %.2fs",
            len(text), len(audio) / sr, time.perf_counter() - t0,
        )
        return audio, int(sr)

    async def synthesize_stream(self, text: str, language: str | None = None):
        """Generate JARVIS voice via ElevenLabs and yield chunks per sentence."""
        import asyncio
        del language
        
        # Simple sentence splitter
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        sentences: list[str] = []
        buf = ""
        for p in parts:
            if len(buf) + len(p) < 300:
                buf = f"{buf} {p}".strip() if buf else p
            else:
                if buf:
                    sentences.append(buf)
                buf = p
        if buf:
            sentences.append(buf)
        if not sentences:
            sentences = [text]

        for sentence in sentences:
            try:
                audio, sr = await asyncio.to_thread(self.synthesize, sentence)
                yield audio, sr
            except Exception as exc:
                logger.warning("ElevenLabs failed on %r: %s", sentence[:40], exc)
                continue

    def check_auth(self) -> dict[str, Any]:
        """Verify API key works and has needed permissions."""
        if not self.api_key:
            return {"ok": False, "error": "No API key"}
        try:
            client = self._client_lazy()
            voices = client.voices.get_all()
            return {
                "ok": True,
                "voices_count": len(voices.voices) if hasattr(voices, "voices") else 0,
                "voice_id": self.voice_id,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


# Public API (matches tts_engine.py interface)

_engine: ElevenLabsEngine | None = None


def _get_engine() -> ElevenLabsEngine:
    global _engine
    if _engine is None:
        _engine = ElevenLabsEngine()
    return _engine


def load_models() -> None:
    """No-op for ElevenLabs (cloud). Just verifies auth."""
    engine = _get_engine()
    status = engine.check_auth()
    if not status.get("ok"):
        raise RuntimeError(f"ElevenLabs auth failed: {status.get('error')}")
    logger.info("ElevenLabs ready (voices=%s)", status.get("voices_count"))


def is_loaded() -> bool:
    """ElevenLabs is 'loaded' if API key is valid."""
    engine = _get_engine()
    return bool(engine.api_key)


def generate_audio(text: str, language: str | None = None) -> tuple[np.ndarray, int]:
    """Generate audio via ElevenLabs."""
    return _get_engine().synthesize(text, language)


async def generate_audio_stream(text: str, language: str | None = None):
    """Stream audio via ElevenLabs."""
    async for chunk in _get_engine().synthesize_stream(text, language):
        yield chunk


def audio_to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    """Convert audio array to WAV bytes."""
    import io
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()
