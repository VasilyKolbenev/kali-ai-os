"""Local TTS microservice — Silero TTS + ONNX RVC JARVIS voice.

Ultra-fast voice synthesis (single process, no WSL):
- Silero TTS v4 (CPU, ~0.06s per phrase)
- ONNX RVC voice conversion to trained JARVIS model (~1-2s)
- EQ post-processing matched to JARVIS Sound Pack
- Total latency ~2s per phrase
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
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS
from scipy.ndimage import gaussian_filter1d

from services.tts.rvc_onnx import RVCEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SILERO_SPEAKER = os.environ.get("SILERO_SPEAKER", "eugene")
SILERO_SR = 48000
RVC_ENABLED = os.environ.get("RVC_ENABLED", "1") == "1"
RVC_PITCH_SHIFT = int(os.environ.get("RVC_PITCH_SHIFT", "5"))
RVC_INDEX_INFLUENCE = float(os.environ.get("RVC_INDEX_INFLUENCE", "0.8"))
MODEL_SR = 40000  # RVC output sample rate

MODELS_DIR = Path(__file__).parent.parent.parent / "models"

# EQ profile matched to JARVIS Sound Pack (FINAL1 tuning)
EQ_BANDS = [
    (20, 800, 0.30),      # low cut
    (800, 2000, 1.30),    # mid clarity boost
    (2000, 4000, 0.65),   # upper-mid cut (mud)
    (4000, 6000, 0.20),   # presence cut (harshness)
    (6000, 10000, 0.45),  # brilliance cut
]

# Global state
tts_model = None
rvc_engine: RVCEngine | None = None


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------
def get_tts_model():
    """Load Silero TTS v4 model."""
    global tts_model

    if tts_model is not None:
        return tts_model

    logger.info("Loading Silero TTS v4 (speaker: %s)...", SILERO_SPEAKER)
    torch.hub._validate_not_a_forked_repo = lambda a, b, c: True

    tts_model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker="v4_ru",
        trust_repo=True,
    )

    # Warmup
    logger.info("Warming up Silero...")
    tts_model.apply_tts(text="Тест системы.", speaker=SILERO_SPEAKER, sample_rate=SILERO_SR)
    logger.info("Silero TTS ready! Speaker: %s", SILERO_SPEAKER)

    return tts_model


def get_rvc_engine() -> RVCEngine:
    """Load ONNX RVC engine with JARVIS v2 model."""
    global rvc_engine

    if rvc_engine is not None:
        return rvc_engine

    logger.info("Loading ONNX RVC engine (JARVIS v2)...")
    rvc_engine = RVCEngine(
        model_path=str(MODELS_DIR / "jarvis_v2.onnx"),
        index_path=str(MODELS_DIR / "jarvis_v2.index"),
        hubert_path=str(MODELS_DIR / "vec-768-layer-12.onnx"),
        rmvpe_path=str(MODELS_DIR / "rmvpe.onnx"),
        index_influence=RVC_INDEX_INFLUENCE,
        model_sr=MODEL_SR,
    )
    rvc_engine.load()
    logger.info("ONNX RVC engine ready!")

    return rvc_engine


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------
def _detect_language(text: str) -> str:
    """Detect language from text (simple heuristic)."""
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    return "ru" if cyrillic > len(text) * 0.3 else "en"


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


def _text_to_ssml(text: str) -> str:
    """Convert plain text to SSML for better intonation and punctuation."""
    text = _fix_stress(text)
    text = _expand_abbreviations(text)

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


def generate_audio(text: str, language: str | None = None) -> tuple[np.ndarray, int]:
    """Generate audio via Silero TTS (SSML), then convert through ONNX RVC + EQ."""
    model = get_tts_model()

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
        engine = get_rvc_engine()
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
    """Convert numpy audio array to WAV bytes."""
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "engine": "silero-v4 + onnx-rvc-v2",
        "loaded": tts_model is not None,
        "speaker": SILERO_SPEAKER,
        "rvc": "loaded" if rvc_engine and rvc_engine.is_loaded else "not loaded",
        "rvc_enabled": RVC_ENABLED,
        "pitch_shift": RVC_PITCH_SHIFT,
        "realtime": True,
    })


@app.route("/synthesize", methods=["POST"])
def synthesize():
    """Synthesize full response at once."""
    data = request.json or {}
    text = data.get("text", "")
    language = data.get("language")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        start = time.perf_counter()
        logger.info("Synthesizing: '%s'", text[:80])

        audio, sr = generate_audio(text, language)
        wav_bytes = audio_to_wav_bytes(audio, sr)
        elapsed = time.perf_counter() - start
        dur = len(audio) / sr

        logger.info(
            "Generated %.1fs audio in %.1fs (RTF=%.2f)",
            dur, elapsed, elapsed / dur,
        )
        return send_file(
            io.BytesIO(wav_bytes), mimetype="audio/wav", download_name="speech.wav",
        )
    except Exception as e:
        logger.exception("TTS failed")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", "3002"))
    logger.info("Starting Silero + ONNX RVC JARVIS voice server on port %d", port)
    get_tts_model()
    if RVC_ENABLED:
        get_rvc_engine()
    app.run(host="0.0.0.0", port=port, debug=False)
