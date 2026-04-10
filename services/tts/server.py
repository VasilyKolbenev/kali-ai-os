"""Local TTS microservice — Qwen3-TTS with cloned JARVIS voice from remaster samples."""

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
tts_model = None
voice_prompt = None

REMASTER_DIR = Path(r"C:\Users\User\Desktop\jarvis-original\resources\sound\voices\jarvis-remaster\ru")
BEST_REF = "joke2.mp3"


def get_model():
    """Lazy-load Qwen3-TTS and encode JARVIS voice."""
    global tts_model, voice_prompt

    if tts_model is None:
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        from qwen_tts import Qwen3TTSModel

        logger.info("Loading Qwen3-TTS Base model...")
        tts_model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base")
        logger.info("Model loaded!")

        # Pre-encode JARVIS voice
        ref_path = str(REMASTER_DIR / BEST_REF)
        if os.path.exists(ref_path):
            logger.info("Encoding JARVIS voice from: %s", ref_path)
            voice_prompt = tts_model.create_voice_clone_prompt(
                ref_audio=ref_path,
                ref_text="Анекдот",
                x_vector_only_mode=True,
            )
            logger.info("JARVIS voice encoded!")
        else:
            logger.warning("Reference not found: %s", ref_path)

    return tts_model


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "engine": "qwen3-tts",
        "model": "Qwen3-TTS-12Hz-1.7B-Base",
        "loaded": tts_model is not None,
        "voice_cloned": voice_prompt is not None,
    })


@app.route("/synthesize", methods=["POST"])
def synthesize():
    """Synthesize speech with cloned JARVIS voice."""
    data = request.json or {}
    text = data.get("text", "")
    language = data.get("language", "russian")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        model = get_model()

        logger.info("Synthesizing [%s]: '%s'", language, text[:80])

        audio_list, sr = model.generate_voice_clone(
            text=text,
            language=language,
            ref_audio=str(REMASTER_DIR / BEST_REF),
            ref_text="Анекдот",
            x_vector_only_mode=True,
            voice_clone_prompt=voice_prompt,
            non_streaming_mode=True,
        )

        buffer = io.BytesIO()
        sf.write(buffer, audio_list[0], sr, format="WAV")
        buffer.seek(0)

        logger.info("Generated %.1fs of audio", len(audio_list[0]) / sr)
        return send_file(buffer, mimetype="audio/wav", download_name="speech.wav")

    except Exception as e:
        logger.exception("TTS failed")
        return jsonify({"error": str(e)}), 500


@app.route("/voices", methods=["GET"])
def list_voices():
    """List available voice references."""
    if not REMASTER_DIR.exists():
        return jsonify({"voices": [], "dir": str(REMASTER_DIR)})
    files = sorted([f.name for f in REMASTER_DIR.glob("*.mp3")])
    return jsonify({"voices": files, "count": len(files), "dir": str(REMASTER_DIR)})


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", "3001"))
    logger.info("Starting Qwen3-TTS JARVIS voice server on port %d", port)

    # Pre-load on startup
    get_model()

    app.run(host="127.0.0.1", port=port, debug=False)
