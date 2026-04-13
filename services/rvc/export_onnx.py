"""One-time script to export RVC PyTorch model to ONNX.

Run from WSL conda rvc environment:
    source ~/miniconda3/etc/profile.d/conda.sh && conda activate rvc
    pip install onnx onnxsim
    python /mnt/c/Users/User/Desktop/Jarvis/services/rvc/export_onnx.py
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def export_rvc_to_onnx(pth_path: str, onnx_path: str) -> None:
    """Export RVC .pth model to ONNX format."""
    logger.info("Loading model from %s...", pth_path)
    cpt = torch.load(pth_path, map_location="cpu", weights_only=False)

    version = cpt.get("version", "v1")
    config = list(cpt["config"])
    vec_channels = 256 if version == "v1" else 768

    logger.info("Model version: %s, vec_channels: %d", version, vec_channels)
    logger.info("Config: %s", config)

    config[-3] = cpt["weight"]["emb_g.weight"].shape[0]

    # Try importing models_onnx from various sources
    models_onnx_cls = None

    # Try Applio
    applio_path = os.path.expanduser("~/Applio")
    if os.path.exists(applio_path):
        sys.path.insert(0, applio_path)
        try:
            from infer.lib.infer_pack.models_onnx import SynthesizerTrnMsNSFsidM
            models_onnx_cls = SynthesizerTrnMsNSFsidM
            logger.info("Using Applio models_onnx")
        except ImportError:
            pass

    # Try RVC WebUI clone
    if models_onnx_cls is None:
        rvc_path = os.path.expanduser("~/rvc-webui")
        if os.path.exists(rvc_path):
            sys.path.insert(0, rvc_path)
            try:
                from infer.lib.infer_pack.models_onnx import SynthesizerTrnMsNSFsidM
                models_onnx_cls = SynthesizerTrnMsNSFsidM
                logger.info("Using RVC WebUI models_onnx")
            except ImportError:
                pass

    if models_onnx_cls is None:
        logger.error(
            "Cannot find models_onnx.py. Clone RVC WebUI:\n"
            "  git clone --depth 1 https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI ~/rvc-webui"
        )
        sys.exit(1)

    logger.info("Building model for ONNX export...")
    net_g = models_onnx_cls(*config, is_half=False, version=version)
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval()

    test_phone = torch.rand(1, 200, vec_channels)
    test_phone_lengths = torch.tensor([200]).long()
    test_pitch = torch.randint(size=(1, 200), low=5, high=255)
    test_pitchf = torch.rand(1, 200)
    test_ds = torch.LongTensor([0])
    test_rnd = torch.rand(1, 192, 200)

    os.makedirs(os.path.dirname(onnx_path), exist_ok=True)

    logger.info("Exporting to %s...", onnx_path)

    # Use legacy exporter with dynamic axes for variable-length input
    torch.onnx.export(
        net_g,
        (test_phone, test_phone_lengths, test_pitch, test_pitchf, test_ds, test_rnd),
        onnx_path,
        dynamic_axes={
            "phone": {1: "seq_len"},
            "pitch": {1: "seq_len"},
            "pitchf": {1: "seq_len"},
            "rnd": {2: "seq_len"},
            "audio": {2: "audio_len"},
        },
        do_constant_folding=False,
        opset_version=13,
        dynamo=False,
        verbose=False,
        input_names=["phone", "phone_lengths", "pitch", "pitchf", "ds", "rnd"],
        output_names=["audio"],
    )

    try:
        import onnx
        import onnxsim

        logger.info("Simplifying ONNX model...")
        model = onnx.load(onnx_path)
        model_simp, check = onnxsim.simplify(model)
        if check:
            onnx.save(model_simp, onnx_path)
            logger.info("ONNX model simplified!")
        else:
            logger.warning("Simplification failed validation, keeping original")
    except ImportError:
        logger.warning("onnxsim not installed, skipping simplification")

    file_size = os.path.getsize(onnx_path) / 1024 / 1024
    logger.info("Done! Exported: %s (%.1f MB)", onnx_path, file_size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export RVC model to ONNX")
    parser.add_argument(
        "--model",
        default=os.path.expanduser(
            "~/Applio/logs/jarvis_v1/jarvis_v1_300e_4500s_best_epoch.pth"
        ),
    )
    parser.add_argument(
        "--output",
        default="/mnt/c/Users/User/Desktop/Jarvis/models/jarvis_v1.onnx",
    )
    args = parser.parse_args()
    export_rvc_to_onnx(args.model, args.output)
