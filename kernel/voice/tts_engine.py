"""In-process TTS engine — Silero TTS v4 + ONNX RVC + JARVIS EQ.

Extracted from services/tts/server.py to run inside the kernel process.
No separate Flask server needed.
"""

import io
import logging
import os
import re
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from scipy.ndimage import gaussian_filter1d

from services.tts.rvc_onnx import RVCEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SILERO_SPEAKER = os.environ.get("SILERO_SPEAKER", "eugene")
SILERO_SR = 48000
RVC_ENABLED = os.environ.get("RVC_ENABLED", "1") == "1"
RVC_PITCH_SHIFT = int(os.environ.get("RVC_PITCH_SHIFT", "5"))
RVC_INDEX_INFLUENCE = float(os.environ.get("RVC_INDEX_INFLUENCE", "0.8"))
MODEL_SR = 40000  # RVC output sample rate

# Models dir: AppData for installed mode, project root for dev
import sys as _sys
if hasattr(_sys, "_MEIPASS"):
    MODELS_DIR = Path(os.environ.get("APPDATA", "")) / "KALI" / "models"
else:
    MODELS_DIR = Path(__file__).parent.parent.parent / "models"

# EQ profile — JARVIS voice, more natural/alive sounding
EQ_BANDS = [
    (20, 300, 0.45),      # sub-bass: warmer, not hollow
    (300, 800, 0.75),     # low-mid: body of voice
    (800, 2000, 1.20),    # mid clarity: slightly boosted
    (2000, 4000, 0.80),   # upper-mid: keep more for articulation
    (4000, 6000, 0.40),   # presence: less harsh but still present
    (6000, 10000, 0.55),  # brilliance: keep some air/sparkle
]

# Global state
_tts_model = None
_rvc_engine: RVCEngine | None = None
_loaded = False


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------
def _get_tts_model():
    """Load Silero TTS v4 model (lazy, cached)."""
    global _tts_model

    if _tts_model is not None:
        return _tts_model

    logger.info("Loading Silero TTS v4 (speaker: %s)...", SILERO_SPEAKER)
    torch.hub._validate_not_a_forked_repo = lambda a, b, c: True

    _tts_model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker="v4_ru",
        trust_repo=True,
    )

    # Warmup
    logger.info("Warming up Silero...")
    _tts_model.apply_tts(text="Тест системы.", speaker=SILERO_SPEAKER, sample_rate=SILERO_SR)
    logger.info("Silero TTS ready! Speaker: %s", SILERO_SPEAKER)

    return _tts_model


def _get_rvc_engine() -> RVCEngine:
    """Load ONNX RVC engine with JARVIS v2 model (lazy, cached)."""
    global _rvc_engine

    if _rvc_engine is not None:
        return _rvc_engine

    logger.info("Loading ONNX RVC engine (JARVIS v2)...")
    _rvc_engine = RVCEngine(
        model_path=str(MODELS_DIR / "jarvis_v2.onnx"),
        index_path=str(MODELS_DIR / "jarvis_v2.index"),
        hubert_path=str(MODELS_DIR / "vec-768-layer-12.onnx"),
        rmvpe_path=str(MODELS_DIR / "rmvpe.onnx"),
        index_influence=RVC_INDEX_INFLUENCE,
        model_sr=MODEL_SR,
    )
    _rvc_engine.load()
    logger.info("ONNX RVC engine ready!")

    return _rvc_engine


def load_models() -> None:
    """Load Silero TTS + RVC ONNX models. Call once at startup.

    Safe to call multiple times -- skips if already loaded.
    """
    global _loaded

    if _loaded:
        return

    _get_tts_model()
    if RVC_ENABLED:
        _get_rvc_engine()
    _loaded = True
    logger.info("TTS engine fully loaded (Silero + RVC ONNX)")


def is_loaded() -> bool:
    """Check if TTS models are loaded."""
    return _loaded


# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------

# Stress correction dictionary — ONLY words Silero gets wrong
_STRESS_MAP = {
    "джарвис": "дж+арвис",
    "связи": "св+язи",
    "связей": "св+язей",
}


def _fix_stress(text: str) -> str:
    """Apply stress corrections from dictionary (case-insensitive)."""
    text_lower = text.lower()
    for word, stressed in _STRESS_MAP.items():
        if word in text_lower:
            text = re.sub(
                rf"\b{re.escape(word)}\b",
                stressed,
                text,
                flags=re.IGNORECASE,
            )
    return text


# Abbreviation pronunciation map (English/tech terms → Russian phonetic)
_ABBREV_MAP = {
    "API": "эй пи ай",
    "UI": "ю ай",
    "URL": "ю эр эл",
    "HTTP": "эйч ти ти пи",
    "HTTPS": "эйч ти ти пи эс",
    "HTML": "эйч ти эм эл",
    "CSS": "си эс эс",
    "JSON": "джейсон",
    "SQL": "эс кю эл",
    "GPU": "джи пи ю",
    "CPU": "си пи ю",
    "VRAM": "ви рэм",
    "RAM": "рэм",
    "SSD": "эс эс ди",
    "USB": "ю эс би",
    "AI": "эй ай",
    "ML": "эм эл",
    "LLM": "эл эл эм",
    "TTS": "ти ти эс",
    "STT": "эс ти ти",
    "RVC": "эр ви си",
    "WSL": "дабл ю эс эл",
    "SSH": "эс эс эйч",
    "VPN": "ви пи эн",
    "DNS": "ди эн эс",
    "IP": "ай пи",
    "OS": "о эс",
    "ID": "ай ди",
    "OK": "окей",
    "CORS": "корс",
    "REST": "рест",
    "CRUD": "крад",
    "CLI": "си эл ай",
    "SDK": "эс ди кей",
    "MVP": "эм ви пи",
    "KALI": "кали",
    "JARVIS": "джарвис",
}


def _expand_abbreviations(text: str) -> str:
    """Replace English abbreviations with Russian phonetic equivalents."""
    for abbr, phonetic in _ABBREV_MAP.items():
        text = re.sub(rf"\b{abbr}\b", phonetic, text)
    return text


def _numbers_to_words(text: str) -> str:
    """Convert digits to Russian words for Silero TTS pronunciation."""
    _ONES = {
        "0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре",
        "5": "пять", "6": "шесть", "7": "семь", "8": "восемь", "9": "девять",
        "10": "десять", "11": "одиннадцать", "12": "двенадцать",
        "13": "тринадцать", "14": "четырнадцать", "15": "пятнадцать",
        "16": "шестнадцать", "17": "семнадцать", "18": "восемнадцать",
        "19": "девятнадцать",
    }
    _TENS = {
        "2": "двадцать", "3": "тридцать", "4": "сорок", "5": "пятьдесят",
        "6": "шестьдесят", "7": "семьдесят", "8": "восемьдесят", "9": "девяносто",
    }
    _HUNDREDS = {
        "1": "сто", "2": "двести", "3": "триста", "4": "четыреста",
        "5": "пятьсот", "6": "шестьсот", "7": "семьсот", "8": "восемьсот",
        "9": "девятьсот",
    }

    def _n2w(n: str) -> str:
        n = n.lstrip("0") or "0"
        if n in _ONES:
            return _ONES[n]
        if len(n) == 2:
            if n[0] == "1":
                return _ONES.get(n, n)
            return f"{_TENS.get(n[0], '')} {_ONES.get(n[1], '')}".strip()
        if len(n) == 3:
            h = _HUNDREDS.get(n[0], "")
            r = _n2w(n[1:])
            return f"{h} {r}".strip() if r != "ноль" else h
        if len(n) <= 6:
            th = _n2w(n[:-3])
            r = _n2w(n[-3:])
            result = f"{th} тысяч"
            return f"{result} {r}" if r != "ноль" else result
        return n

    def _repl(m: re.Match) -> str:
        num = m.group(0)
        if "." in num:
            p = num.split(".")
            return f"{_n2w(p[0])} точка {_n2w(p[1])}"
        return _n2w(num)

    # Also strip markdown bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return re.sub(r"\d+\.?\d*", _repl, text)


def _text_to_ssml(text: str) -> str:
    """Convert plain text to SSML for better intonation and punctuation."""
    text = _fix_stress(text)
    text = _expand_abbreviations(text)
    text = _numbers_to_words(text)

    # Escape XML special chars
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Handle quoted text — wrap in emphasis
    text = re.sub(
        r'["\u201c\u201d\u00ab\u00bb]([^"\u201c\u201d\u00ab\u00bb]+)["\u201c\u201d\u00ab\u00bb]',
        r'<emphasis level="moderate">\1</emphasis>',
        text,
    )

    # Em dash — pause 200ms
    text = re.sub(r"\s*\u2014\s*", r' <break time="200ms"/> ', text)

    # Hyphen between words: "слово - слово" → pause 120ms
    text = re.sub(r"\s+-\s+", r' <break time="120ms"/> ', text)

    # Wrap exclamatory sentences in prosody
    text = re.sub(
        r"([^.!?<>]+!)",
        r'<prosody pitch="+5%" rate="103%">\1</prosody>',
        text,
    )

    # Wrap questions in prosody (rising intonation)
    text = re.sub(
        r"([^.!?<>]+\?)",
        r'<prosody pitch="+8%" rate="98%">\1</prosody>',
        text,
    )

    # Add breaks after sentence punctuation
    text = re.sub(r"([.!])\s+", r'\1<break time="350ms"/> ', text)
    text = re.sub(r"([?])\s+", r'\1<break time="400ms"/> ', text)
    text = re.sub(r"([,;:])\s+", r'\1<break time="150ms"/> ', text)

    return f"<speak>{text}</speak>"


def _detect_language(text: str) -> str:
    """Detect language from text (simple heuristic)."""
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    return "ru" if cyrillic > len(text) * 0.3 else "en"


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _apply_eq(audio: np.ndarray, sr: int) -> np.ndarray:
    """Apply JARVIS Sound Pack matched EQ via FFT."""
    spectrum = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)

    gains = np.ones_like(freqs)
    for low, high, gain in EQ_BANDS:
        mask = (freqs >= low) & (freqs < high)
        gains[mask] = gain

    gains = gaussian_filter1d(gains, sigma=8)
    result = np.fft.irfft(spectrum * gains, n=len(audio))
    return result.astype(np.float32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_audio(text: str, language: str | None = None) -> tuple[np.ndarray, int]:
    """Full pipeline: SSML → Silero → RVC → EQ → normalized audio.

    Args:
        text: Input text to synthesize.
        language: Language hint ('ru' or 'en'). Auto-detected if None.

    Returns:
        Tuple of (audio array float32, sample_rate int).
    """
    model = _get_tts_model()

    if language is None:
        language = _detect_language(text)

    ssml = _text_to_ssml(text)
    logger.debug("SSML: %s", ssml[:120])

    t0 = time.perf_counter()
    try:
        audio_tensor = model.apply_tts(
            ssml_text=ssml, speaker=SILERO_SPEAKER, sample_rate=SILERO_SR,
        )
    except Exception:
        logger.warning("SSML failed, falling back to plain text")
        audio_tensor = model.apply_tts(
            text=text, speaker=SILERO_SPEAKER, sample_rate=SILERO_SR,
        )
    audio = audio_tensor.numpy()
    t_tts = time.perf_counter() - t0

    sr = SILERO_SR

    if RVC_ENABLED:
        t1 = time.perf_counter()
        engine = _get_rvc_engine()
        audio = engine.convert(audio, sr=sr, pitch_shift=RVC_PITCH_SHIFT)
        sr = MODEL_SR
        t_rvc = time.perf_counter() - t1

        # Apply JARVIS EQ
        audio = _apply_eq(audio, sr)
    else:
        t_rvc = 0.0

    # Normalize to good volume
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = (audio * 0.7 / peak).astype(np.float32)

    logger.info(
        "Timing: Silero=%.2fs RVC=%.2fs total=%.2fs",
        t_tts, t_rvc, t_tts + t_rvc,
    )

    return audio, sr


def audio_to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    """Convert numpy audio array to WAV bytes.

    Args:
        audio: Audio array (float32).
        sr: Sample rate in Hz.

    Returns:
        WAV file as bytes.
    """
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()
