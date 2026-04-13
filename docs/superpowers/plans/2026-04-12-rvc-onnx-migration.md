# RVC ONNX Migration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PyTorch/fairseq RVC inference with ONNX Runtime, eliminating WSL dependency.

**Architecture:** Export trained JARVIS RVC model to ONNX format, download pre-built HuBERT and RMVPE ONNX models, write new ONNX-based inference server that runs on native Windows Python with GPU acceleration.

**Tech Stack:** onnxruntime-gpu, faiss-cpu, numpy, soundfile, flask

**Spec:** `docs/superpowers/specs/2026-04-12-kali-desktop-production-design.md`

---

## File Structure

```
services/
├── tts/
│   ├── server.py              # MODIFY: add ONNX RVC in-process (replace HTTP call to RVC)
│   └── rvc_onnx.py            # CREATE: ONNX RVC inference engine
├── rvc/
│   ├── server.py              # KEEP (legacy, not used in new pipeline)
│   └── export_onnx.py         # CREATE: one-time export script (runs in WSL)
models/                         # CREATE: directory for ONNX models
├── jarvis_v1.onnx             # Exported RVC model
├── jarvis_v1.index            # FAISS index (copied from WSL)
├── vec-768-layer-12.onnx      # HuBERT feature extractor
└── rmvpe.onnx                 # Pitch estimator
tests/
└── test_rvc_onnx.py           # CREATE: tests for ONNX RVC inference
```

---

## Chunk 1: Export RVC Model to ONNX

### Task 1: Create export script

**Files:**
- Create: `services/rvc/export_onnx.py`

This task runs in WSL conda `rvc` environment where PyTorch + fairseq work.

- [ ] **Step 1: Write the export script**

```python
"""One-time script to export RVC PyTorch model to ONNX.

Run from WSL conda rvc environment:
    conda activate rvc
    python services/rvc/export_onnx.py
"""

import argparse
import os
import sys
from pathlib import Path

import torch


def export_rvc_to_onnx(pth_path: str, onnx_path: str) -> None:
    """Export RVC .pth model to ONNX format."""
    print(f"Loading model from {pth_path}...")
    cpt = torch.load(pth_path, map_location="cpu", weights_only=False)

    # Detect model version
    version = cpt.get("version", "v1")
    config = cpt["config"]
    vec_channels = 256 if version == "v1" else 768

    print(f"Model version: {version}, vec_channels: {vec_channels}")
    print(f"Config: {config}")

    # Fix config for ONNX export
    config[-3] = cpt["weight"]["emb_g.weight"].shape[0]

    # Try importing from Applio/RVC
    try:
        sys.path.insert(0, os.path.expanduser("~/Applio"))
        from infer.lib.infer_pack.models_onnx import SynthesizerTrnMsNSFsidM
    except ImportError:
        print("ERROR: Cannot import models_onnx. Trying RVC WebUI...")
        try:
            from rvc.lib.infer_pack.models_onnx import SynthesizerTrnMsNSFsidM
        except ImportError:
            print("ERROR: Need Applio or RVC WebUI with models_onnx.py")
            print("Clone: git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI")
            sys.exit(1)

    # Build model
    net_g = SynthesizerTrnMsNSFsidM(*config, is_half=False, version=version)
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval()

    # Create test inputs
    test_phone = torch.rand(1, 200, vec_channels)
    test_phone_lengths = torch.tensor([200]).long()
    test_pitch = torch.randint(size=(1, 200), low=5, high=255)
    test_pitchf = torch.rand(1, 200)
    test_ds = torch.LongTensor([0])
    test_rnd = torch.rand(1, 192, 200)

    print(f"Exporting to {onnx_path}...")
    torch.onnx.export(
        net_g,
        (test_phone, test_phone_lengths, test_pitch, test_pitchf, test_ds, test_rnd),
        onnx_path,
        dynamic_axes={
            "phone": [1],
            "pitch": [1],
            "pitchf": [1],
            "rnd": [2],
        },
        do_constant_folding=False,
        opset_version=18,
        verbose=False,
        input_names=["phone", "phone_lengths", "pitch", "pitchf", "ds", "rnd"],
        output_names=["audio"],
    )

    # Simplify if onnxsim available
    try:
        import onnx
        import onnxsim
        model = onnx.load(onnx_path)
        model_simp, check = onnxsim.simplify(model)
        if check:
            onnx.save(model_simp, onnx_path)
            print("ONNX model simplified!")
    except ImportError:
        print("onnxsim not installed, skipping simplification")

    file_size = os.path.getsize(onnx_path) / 1024 / 1024
    print(f"Done! Exported: {onnx_path} ({file_size:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export RVC model to ONNX")
    parser.add_argument(
        "--model",
        default=os.path.expanduser(
            "~/Applio/logs/jarvis_v1/jarvis_v1_300e_4500s_best_epoch.pth"
        ),
        help="Path to .pth model file",
    )
    parser.add_argument(
        "--output",
        default="/mnt/c/Users/User/Desktop/Jarvis/models/jarvis_v1.onnx",
        help="Output .onnx path",
    )
    args = parser.parse_args()
    export_rvc_to_onnx(args.model, args.output)
```

- [ ] **Step 2: Create models directory**

```bash
mkdir -p /mnt/c/Users/User/Desktop/Jarvis/models
```

- [ ] **Step 3: Run export in WSL**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate rvc
pip install onnx onnxsim 2>/dev/null
python /mnt/c/Users/User/Desktop/Jarvis/services/rvc/export_onnx.py
```

Expected output: `Done! Exported: .../models/jarvis_v1.onnx (XX.X MB)`

If `models_onnx.py` not found in Applio — clone RVC WebUI:
```bash
cd ~ && git clone --depth 1 https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI rvc-webui
# Then update sys.path in script to point to ~/rvc-webui
```

- [ ] **Step 4: Copy FAISS index**

```bash
cp ~/Applio/logs/jarvis_v1/jarvis_v1.index /mnt/c/Users/User/Desktop/Jarvis/models/
```

- [ ] **Step 5: Download pre-built ONNX models**

```bash
cd /mnt/c/Users/User/Desktop/Jarvis/models

# HuBERT feature extractor
wget -O vec-768-layer-12.onnx "https://huggingface.co/MidFord327/Hubert-Base-ONNX/resolve/main/vec-768-layer-12.onnx"

# RMVPE pitch estimator
wget -O rmvpe.onnx "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.onnx"
```

If HuggingFace URLs fail — export manually from PyTorch (separate task).

- [ ] **Step 6: Verify all model files exist**

```bash
ls -lh /mnt/c/Users/User/Desktop/Jarvis/models/
# Expected:
# jarvis_v1.onnx   (~60-80 MB)
# jarvis_v1.index   (~XX MB)
# vec-768-layer-12.onnx (~380 MB)
# rmvpe.onnx        (~362 MB)
```

- [ ] **Step 7: Commit**

```bash
git add services/rvc/export_onnx.py models/.gitkeep
git commit -m "feat: add RVC ONNX export script and models directory"
```

Note: .onnx files go in .gitignore (too large for git). Add to models/.gitignore:
```
*.onnx
*.index
```

---

## Chunk 2: ONNX RVC Inference Engine

### Task 2: Write ONNX RVC inference module

**Files:**
- Create: `services/tts/rvc_onnx.py`
- Create: `tests/test_rvc_onnx.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for ONNX RVC inference engine."""

import numpy as np
import pytest
from pathlib import Path

MODELS_DIR = Path(__file__).parent.parent / "models"


@pytest.fixture
def rvc_engine():
    """Create RVC ONNX engine with JARVIS model."""
    from services.tts.rvc_onnx import RVCEngine

    return RVCEngine(
        model_path=str(MODELS_DIR / "jarvis_v1.onnx"),
        index_path=str(MODELS_DIR / "jarvis_v1.index"),
        hubert_path=str(MODELS_DIR / "vec-768-layer-12.onnx"),
        rmvpe_path=str(MODELS_DIR / "rmvpe.onnx"),
    )


@pytest.mark.skipif(
    not (MODELS_DIR / "jarvis_v1.onnx").exists(),
    reason="ONNX models not exported yet",
)
class TestRVCEngine:
    def test_convert_returns_audio(self, rvc_engine):
        """Converting audio returns non-empty float32 array."""
        input_audio = np.random.randn(24000).astype(np.float32) * 0.1
        result = rvc_engine.convert(input_audio, sr=24000)
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert len(result) > 0

    def test_convert_preserves_duration(self, rvc_engine):
        """Output duration should be similar to input (~20% tolerance)."""
        duration_s = 2.0
        sr = 24000
        input_audio = np.random.randn(int(duration_s * sr)).astype(np.float32) * 0.1
        result = rvc_engine.convert(input_audio, sr=sr)
        output_duration = len(result) / 40000  # RVC outputs at 40kHz
        assert abs(output_duration - duration_s) / duration_s < 0.3

    def test_convert_different_sample_rates(self, rvc_engine):
        """Engine handles 24kHz and 48kHz input."""
        for sr in [24000, 48000]:
            audio = np.random.randn(sr * 2).astype(np.float32) * 0.1
            result = rvc_engine.convert(audio, sr=sr)
            assert len(result) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\Users\User\Desktop\Jarvis
uv run pytest tests/test_rvc_onnx.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.tts.rvc_onnx'`

- [ ] **Step 3: Write ONNX RVC inference engine**

```python
"""ONNX-based RVC voice conversion — no fairseq, no WSL, native Windows.

Replaces the PyTorch-based RVC server with pure ONNX Runtime inference.
Requires: onnxruntime-gpu (or onnxruntime-directml), faiss-cpu, numpy, soundfile.
"""

import logging
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class RVCEngine:
    """RVC voice conversion using ONNX Runtime.

    Pipeline: audio → resample 16kHz → HuBERT features → RMVPE pitch →
              RVC model → output audio (40kHz)
    """

    def __init__(
        self,
        model_path: str,
        index_path: str | None = None,
        hubert_path: str | None = None,
        rmvpe_path: str | None = None,
        index_influence: float = 0.8,
        device: str = "auto",
    ) -> None:
        self.model_path = model_path
        self.index_path = index_path
        self.hubert_path = hubert_path
        self.rmvpe_path = rmvpe_path
        self.index_influence = index_influence

        self._rvc_session = None
        self._hubert_session = None
        self._rmvpe_session = None
        self._faiss_index = None
        self._device = device
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load all ONNX models and FAISS index."""
        import onnxruntime as ort

        providers = self._get_providers()
        logger.info("ONNX providers: %s", providers)

        # Load RVC model
        logger.info("Loading RVC ONNX model...")
        self._rvc_session = ort.InferenceSession(self.model_path, providers=providers)

        # Load HuBERT
        if self.hubert_path and Path(self.hubert_path).exists():
            logger.info("Loading HuBERT ONNX...")
            self._hubert_session = ort.InferenceSession(
                self.hubert_path, providers=providers,
            )

        # Load RMVPE
        if self.rmvpe_path and Path(self.rmvpe_path).exists():
            logger.info("Loading RMVPE ONNX...")
            self._rmvpe_session = ort.InferenceSession(
                self.rmvpe_path, providers=providers,
            )

        # Load FAISS index
        if self.index_path and Path(self.index_path).exists():
            try:
                import faiss

                self._faiss_index = faiss.read_index(self.index_path)
                logger.info("FAISS index loaded: %d vectors", self._faiss_index.ntotal)
            except Exception as e:
                logger.warning("FAISS index load failed (continuing without): %s", e)

        self._loaded = True
        logger.info("RVC ONNX engine ready!")

    def _get_providers(self) -> list[str]:
        """Select ONNX Runtime execution providers."""
        import onnxruntime as ort

        available = ort.get_available_providers()

        if self._device == "auto":
            if "CUDAExecutionProvider" in available:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "DmlExecutionProvider" in available:
                return ["DmlExecutionProvider", "CPUExecutionProvider"]
            return ["CPUExecutionProvider"]

        return ["CPUExecutionProvider"]

    def convert(
        self, audio: np.ndarray, sr: int = 24000, pitch_shift: int = 0,
    ) -> np.ndarray:
        """Convert audio to JARVIS voice.

        Args:
            audio: Input audio as float32 numpy array.
            sr: Sample rate of input audio.
            pitch_shift: Semitones to shift pitch (0 = no change).

        Returns:
            Converted audio as float32 numpy array (40kHz).
        """
        if not self._loaded:
            self.load()

        t0 = time.perf_counter()

        # Resample to 16kHz for HuBERT
        audio_16k = self._resample(audio, sr, 16000)

        # Extract HuBERT features
        t1 = time.perf_counter()
        feats = self._extract_hubert(audio_16k)
        t_hubert = time.perf_counter() - t1

        # Extract pitch with RMVPE
        t2 = time.perf_counter()
        pitch, pitchf = self._extract_pitch(audio_16k, pitch_shift)
        t_pitch = time.perf_counter() - t2

        # Apply FAISS index (retrieval)
        if self._faiss_index is not None and self.index_influence > 0:
            feats = self._apply_index(feats)

        # Run RVC model
        t3 = time.perf_counter()
        output = self._run_rvc(feats, pitch, pitchf)
        t_rvc = time.perf_counter() - t3

        total = time.perf_counter() - t0
        logger.info(
            "RVC ONNX: HuBERT=%.2fs pitch=%.2fs rvc=%.2fs total=%.2fs",
            t_hubert, t_pitch, t_rvc, total,
        )

        return output.astype(np.float32)

    def _resample(self, audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
        """Resample audio using linear interpolation."""
        if sr_from == sr_to:
            return audio
        ratio = sr_to / sr_from
        new_len = int(len(audio) * ratio)
        return np.interp(
            np.linspace(0, len(audio) - 1, new_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    def _extract_hubert(self, audio_16k: np.ndarray) -> np.ndarray:
        """Extract HuBERT features from 16kHz audio."""
        if self._hubert_session is None:
            raise RuntimeError("HuBERT model not loaded")

        # HuBERT expects [batch, sequence]
        input_data = audio_16k.reshape(1, -1).astype(np.float32)
        outputs = self._hubert_session.run(None, {"audio": input_data})
        return outputs[0]  # [1, seq_len, 768]

    def _extract_pitch(
        self, audio_16k: np.ndarray, pitch_shift: int = 0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Extract pitch using RMVPE."""
        if self._rmvpe_session is None:
            # Fallback: zero pitch (will still work, just less accurate)
            seq_len = len(audio_16k) // 160  # ~10ms hop
            return np.zeros((1, seq_len), dtype=np.int64), np.zeros(
                (1, seq_len), dtype=np.float32,
            )

        input_data = audio_16k.reshape(1, -1).astype(np.float32)
        outputs = self._rmvpe_session.run(None, {"audio": input_data})
        pitch = outputs[0]  # [1, seq_len]

        if pitch_shift != 0:
            pitch = pitch * (2 ** (pitch_shift / 12))

        pitchf = pitch.astype(np.float32)
        pitch_int = np.round(pitch).astype(np.int64)

        return pitch_int, pitchf

    def _apply_index(self, feats: np.ndarray) -> np.ndarray:
        """Apply FAISS index retrieval for voice similarity."""
        if self._faiss_index is None:
            return feats

        # feats: [1, seq_len, 768]
        feat_2d = feats.reshape(-1, feats.shape[-1]).astype(np.float32)
        _, indices = self._faiss_index.search(feat_2d, 1)
        retrieved = np.array(
            [self._faiss_index.reconstruct(int(idx)) for idx in indices[:, 0]],
        )

        # Blend original and retrieved features
        alpha = self.index_influence
        blended = feat_2d * (1 - alpha) + retrieved * alpha
        return blended.reshape(feats.shape).astype(np.float32)

    def _run_rvc(
        self, feats: np.ndarray, pitch: np.ndarray, pitchf: np.ndarray,
    ) -> np.ndarray:
        """Run the RVC ONNX model."""
        if self._rvc_session is None:
            raise RuntimeError("RVC model not loaded")

        seq_len = feats.shape[1]

        # Align pitch length to feature length
        if pitch.shape[1] != seq_len:
            pitch = np.interp(
                np.linspace(0, pitch.shape[1] - 1, seq_len),
                np.arange(pitch.shape[1]),
                pitch[0],
            ).reshape(1, -1).astype(np.int64)
            pitchf = np.interp(
                np.linspace(0, pitchf.shape[1] - 1, seq_len),
                np.arange(pitchf.shape[1]),
                pitchf[0],
            ).reshape(1, -1).astype(np.float32)

        phone_lengths = np.array([seq_len], dtype=np.int64)
        ds = np.array([0], dtype=np.int64)
        rnd = np.random.randn(1, 192, seq_len).astype(np.float32)

        outputs = self._rvc_session.run(
            None,
            {
                "phone": feats.astype(np.float32),
                "phone_lengths": phone_lengths,
                "pitch": pitch,
                "pitchf": pitchf,
                "ds": ds,
                "rnd": rnd,
            },
        )

        return outputs[0].squeeze()
```

- [ ] **Step 4: Install ONNX dependencies (Windows)**

```powershell
cd C:\Users\User\Desktop\Jarvis
uv add onnxruntime-gpu faiss-cpu
```

If `onnxruntime-gpu` fails (CUDA version mismatch):
```powershell
uv add onnxruntime faiss-cpu
```

- [ ] **Step 5: Run tests**

```bash
cd C:\Users\User\Desktop\Jarvis
uv run pytest tests/test_rvc_onnx.py -v
```

Expected: PASS (if models exported) or SKIP (if models not yet available)

- [ ] **Step 6: Manual voice quality test**

```python
# Quick test script — compare ONNX vs PyTorch output
import soundfile as sf
from services.tts.rvc_onnx import RVCEngine

engine = RVCEngine(
    model_path="models/jarvis_v1.onnx",
    index_path="models/jarvis_v1.index",
    hubert_path="models/vec-768-layer-12.onnx",
    rmvpe_path="models/rmvpe.onnx",
)
engine.load()

# Load a test audio file
audio, sr = sf.read("path/to/test_input.wav")
result = engine.convert(audio, sr=sr)
sf.write("test_onnx_output.wav", result, 40000)
# Compare with test_SILERO_RVC.wav
```

- [ ] **Step 7: Commit**

```bash
git add services/tts/rvc_onnx.py tests/test_rvc_onnx.py
git commit -m "feat: add ONNX-based RVC inference engine"
```

---

## Chunk 3: Merge into TTS Server

### Task 3: Update TTS server to use ONNX RVC in-process

**Files:**
- Modify: `services/tts/server.py`

- [ ] **Step 1: Replace HTTP RVC call with in-process ONNX**

In `server.py`, replace `_apply_rvc()` HTTP call with direct `RVCEngine.convert()`:

```python
# At top of file, add:
from services.tts.rvc_onnx import RVCEngine

# Global state — add:
rvc_engine = None

# In model loading section, add:
def get_rvc_engine():
    global rvc_engine
    if rvc_engine is not None:
        return rvc_engine
    models_dir = Path(__file__).parent.parent.parent / "models"
    rvc_engine = RVCEngine(
        model_path=str(models_dir / "jarvis_v1.onnx"),
        index_path=str(models_dir / "jarvis_v1.index"),
        hubert_path=str(models_dir / "vec-768-layer-12.onnx"),
        rmvpe_path=str(models_dir / "rmvpe.onnx"),
    )
    rvc_engine.load()
    return rvc_engine

# In generate_audio(), replace _apply_rvc() call with:
    if RVC_ENABLED:
        engine = get_rvc_engine()
        t1 = time.perf_counter()
        audio = engine.convert(audio, sr=sr)
        sr = 40000  # RVC outputs at 40kHz
        t_rvc = time.perf_counter() - t1
```

- [ ] **Step 2: Remove old HTTP RVC client code**

Delete `_apply_rvc()` function and `RVC_URL` config.

- [ ] **Step 3: Update health endpoint**

```python
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "engine": "silero-v4 + rvc-onnx",
        "loaded": tts_model is not None,
        "rvc": "loaded" if rvc_engine and rvc_engine.is_loaded else "not loaded",
        "speaker": SILERO_SPEAKER,
    })
```

- [ ] **Step 4: Benchmark**

```bash
# Start the merged server (no separate RVC server needed!)
python services/tts/server.py

# Test
curl -X POST http://localhost:3002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello test"}' \
  -o test_merged.wav
```

Check server logs for `Timing: Silero=XXs RVC_ONNX=XXs total=XXs`

- [ ] **Step 5: A/B quality test**

Compare `test_merged.wav` with `test_SILERO_RVC.wav` (the approved reference).
They should sound identical — same model weights, different runtime.

- [ ] **Step 6: Commit**

```bash
git add services/tts/server.py
git commit -m "feat: merge ONNX RVC into TTS server (no separate RVC process)"
```

---

## Notes

- After this plan is complete, the RVC server on port 3003 is no longer needed
- The TTS server runs everything in-process: Silero TTS → ONNX RVC → output
- Only one Python process needed for voice: `python services/tts/server.py`
- WSL is no longer required for any voice service
- Next plans: Tauri desktop shell (plan 2), Installer (plan 3)
