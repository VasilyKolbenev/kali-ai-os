"""Local TTS microservice using NeuTTS Air with cloned JARVIS voice."""

import io
import logging
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from flask import Flask, jsonify, request, send_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global state
tts_engine = None
ref_codes = None
ref_text = "Слушаю вас"
REFERENCE_DIR = Path(__file__).parent.parent.parent / "ui" / "public" / "sounds"


def get_engine():
    """Lazy-load NeuTTS engine and encode JARVIS voice reference."""
    global tts_engine, ref_codes

    if tts_engine is None:
        from neutts import NeuTTS

        logger.info("Loading NeuTTS Air model...")
        tts_engine = NeuTTS()
        logger.info("NeuTTS Air loaded")

        # Encode JARVIS voice reference once
        ref_files = ["reply1.mp3", "greet1.mp3", "ok1.mp3"]
        for ref_name in ref_files:
            ref_path = REFERENCE_DIR / ref_name
            if ref_path.exists():
                logger.info("Encoding JARVIS voice from: %s", ref_path)
                ref_codes = tts_engine.encode_reference(str(ref_path))
                logger.info("Voice encoded: shape=%s", ref_codes.shape)
                break

        if ref_codes is None:
            logger.warning("No voice reference found, TTS will use default voice")

    return tts_engine


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "engine": "neutts-air",
        "model": "neuphonic/neutts-nano",
        "loaded": tts_engine is not None,
        "voice_cloned": ref_codes is not None,
    })


@app.route("/synthesize", methods=["POST"])
def synthesize():
    """Synthesize speech from text using cloned JARVIS voice."""
    data = request.json or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        engine = get_engine()

        if ref_codes is None:
            return jsonify({"error": "No voice reference encoded"}), 500

        logger.info("Synthesizing: '%s'", text[:80])

        audio = engine.infer(
            text=text,
            ref_codes=ref_codes,
            ref_text=ref_text,
        )

        buffer = io.BytesIO()
        sf.write(buffer, audio, 24000, format="WAV")
        buffer.seek(0)

        logger.info("Generated %.1fs of audio", len(audio) / 24000)
        return send_file(buffer, mimetype="audio/wav", download_name="speech.wav")

    except Exception as e:
        logger.exception("TTS synthesis failed")
        return jsonify({"error": str(e)}), 500


@app.route("/voices", methods=["GET"])
def list_voices():
    """List available voice reference files."""
    if not REFERENCE_DIR.exists():
        return jsonify({"voices": [], "dir": str(REFERENCE_DIR)})
    files = sorted([f.name for f in REFERENCE_DIR.glob("*.mp3")])
    return jsonify({"voices": files, "count": len(files), "dir": str(REFERENCE_DIR)})


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", "3001"))
    logger.info("Starting NeuTTS Air TTS on port %d", port)
    logger.info("Voice references dir: %s", REFERENCE_DIR)

    # Pre-load model on startup
    get_engine()

    app.run(host="127.0.0.1", port=port, debug=False)
