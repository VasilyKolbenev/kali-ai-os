"""Local TTS microservice using NeuTTS Air with cloned JARVIS voice."""

import io
import logging
import os
import sys
from pathlib import Path

import soundfile as sf
from flask import Flask, jsonify, request, send_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global TTS engine
tts_engine = None
REFERENCE_DIR = Path(__file__).parent.parent.parent / "ui" / "public" / "sounds"


def get_engine():
    """Lazy-load NeuTTS engine."""
    global tts_engine
    if tts_engine is None:
        from neutts import NeuTTS

        logger.info("Loading NeuTTS Air model (first time may download ~500MB)...")
        tts_engine = NeuTTS(backend="torch")
        logger.info("NeuTTS Air loaded successfully")
    return tts_engine


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "engine": "neutts-air", "loaded": tts_engine is not None})


@app.route("/synthesize", methods=["POST"])
def synthesize():
    """Synthesize speech from text using cloned JARVIS voice."""
    data = request.json or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        engine = get_engine()

        # Use JARVIS voice reference (best quality sample)
        ref_path = REFERENCE_DIR / "greet1.mp3"
        if not ref_path.exists():
            # Try any available sample
            samples = list(REFERENCE_DIR.glob("*.mp3"))
            if not samples:
                return jsonify({"error": "No voice reference files found"}), 500
            ref_path = samples[0]

        logger.info("Synthesizing: '%s' (ref: %s)", text[:50], ref_path.name)

        # Generate speech with cloned voice
        audio = engine.say(
            text=text,
            ref_audio=str(ref_path),
            speed=1.0,
        )

        # Convert to MP3 and return
        buffer = io.BytesIO()
        sf.write(buffer, audio["audio"], audio["sample_rate"], format="WAV")
        buffer.seek(0)

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
    logger.info("Starting NeuTTS Air server on port %d", port)
    logger.info("Voice references: %s", REFERENCE_DIR)
    app.run(host="127.0.0.1", port=port, debug=False)
