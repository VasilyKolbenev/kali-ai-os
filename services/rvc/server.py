"""RVC Voice Conversion microservice — converts any voice to JARVIS.

Accepts WAV audio via POST, returns converted WAV with JARVIS voice.
Runs in conda env 'rvc' (Python 3.10) due to fairseq dependency.

Launch:
    conda activate rvc
    python services/rvc/server.py
"""

import io
import logging
import os
import time
from pathlib import Path

import soundfile as sf
import torch
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

# Patch torch.load for fairseq/RVC model compatibility
_orig_torch_load = torch.load


def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_torch_load(*args, **kwargs)


torch.load = _patched_torch_load

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_PATH = os.environ.get(
    "RVC_MODEL",
    os.path.expanduser(
        "~/Applio/logs/jarvis_v1/jarvis_v1_300e_4500s_best_epoch.pth"
    ),
)
INDEX_PATH = os.environ.get(
    "RVC_INDEX",
    os.path.expanduser("~/Applio/logs/jarvis_v1/jarvis_v1.index"),
)
INDEX_INFLUENCE = float(os.environ.get("RVC_INDEX_INFLUENCE", "0.8"))
PITCH_LEVEL = int(os.environ.get("RVC_PITCH", "0"))

# Global state
converter = None


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------
def get_converter():
    """Load RVC converter with JARVIS model."""
    global converter

    if converter is not None:
        return converter

    from infer_rvc_python import BaseLoader

    logger.info("Loading RVC JARVIS model...")
    converter = BaseLoader(only_cpu=False, hubert_path=None, rmvpe_path=None)

    converter.apply_conf(
        tag="jarvis",
        file_model=MODEL_PATH,
        pitch_algo="rmvpe+",
        pitch_lvl=PITCH_LEVEL,
        file_index=INDEX_PATH,
        index_influence=INDEX_INFLUENCE,
    )

    # Warmup with a short audio
    logger.info("Warming up RVC...")
    import numpy as np

    warmup_audio = np.random.randn(24000).astype(np.float32) * 0.01
    warmup_path = "/tmp/rvc_warmup.wav"
    sf.write(warmup_path, warmup_audio, 24000)
    try:
        converter(audio_files=[warmup_path], tag_list=["jarvis"])
    except Exception:
        pass
    logger.info("RVC ready! Model: %s", Path(MODEL_PATH).name)

    return converter


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({
        "status": "ok",
        "engine": "rvc-v2",
        "model": Path(MODEL_PATH).stem,
        "loaded": converter is not None,
    })


@app.route("/convert", methods=["POST"])
def convert():
    """Convert uploaded WAV audio to JARVIS voice.

    Accepts:
        - multipart/form-data with 'audio' file field
        - application/octet-stream with raw WAV bytes in body

    Returns: WAV audio with JARVIS voice.
    """
    conv = get_converter()

    try:
        # Get audio data
        if request.content_type and "multipart" in request.content_type:
            audio_file = request.files.get("audio")
            if not audio_file:
                return jsonify({"error": "No 'audio' file in request"}), 400
            audio_data = audio_file.read()
        else:
            audio_data = request.get_data()

        if not audio_data or len(audio_data) < 100:
            return jsonify({"error": "Empty or invalid audio data"}), 400

        # Save to temp file (RVC needs file path)
        tmp_in = "/tmp/rvc_input.wav"
        with open(tmp_in, "wb") as f:
            f.write(audio_data)

        # Convert
        start = time.perf_counter()
        result = conv(audio_files=[tmp_in], tag_list=["jarvis"])
        elapsed = time.perf_counter() - start

        if not result:
            return jsonify({"error": "RVC conversion returned no output"}), 500

        # Read result and return
        output_path = result[0]
        data, sr = sf.read(output_path)
        logger.info("Converted in %.2fs (%.1fs audio)", elapsed, len(data) / sr)

        buf = io.BytesIO()
        sf.write(buf, data, sr, format="WAV")
        buf.seek(0)

        return send_file(buf, mimetype="audio/wav", download_name="jarvis.wav")

    except Exception as e:
        logger.exception("RVC conversion failed")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("RVC_PORT", "3003"))
    logger.info("Starting RVC JARVIS voice server on port %d", port)
    get_converter()
    app.run(host="0.0.0.0", port=port, debug=False)
