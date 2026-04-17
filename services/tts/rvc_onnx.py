"""ONNX-based RVC voice conversion — no fairseq, no WSL, native Windows.

Pipeline: audio → HuBERT features (768d, 2x repeat) → F0 pitch → RVC synthesis → output
All inference via ONNX Runtime (GPU or CPU).

Based on: third_party/rvc_onnx_infer/infer/lib/infer_pack/onnx_inference.py
"""

import logging
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# F0 range constants
F0_MIN = 50
F0_MAX = 1100
F0_MEL_MIN = 1127 * np.log(1 + F0_MIN / 700)
F0_MEL_MAX = 1127 * np.log(1 + F0_MAX / 700)

# RMVPE constants
RMVPE_N_MEL = 128
RMVPE_HOP = 160
RMVPE_WIN = 1024
RMVPE_CENTS_MAPPING = np.array([10 * i + 1997.3794 for i in range(360)])


def _mel_spectrogram(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Compute mel spectrogram for RMVPE input. Returns [1, 128, time]."""
    n_fft = RMVPE_WIN
    hop_length = RMVPE_HOP
    n_mels = RMVPE_N_MEL

    pad_len = n_fft // 2
    audio_padded = np.pad(audio, (pad_len, pad_len), mode="reflect")
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)

    frames = []
    for start in range(0, len(audio_padded) - n_fft, hop_length):
        frame = audio_padded[start : start + n_fft] * window
        spectrum = np.fft.rfft(frame)
        power = np.abs(spectrum) ** 2
        frames.append(power)

    power_spec = np.array(frames, dtype=np.float32)

    fft_freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    mel_low = 0.0
    mel_high = 2595.0 * np.log10(1.0 + (sr / 2) / 700.0)
    mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
    hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)

    filterbank = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for i in range(n_mels):
        low, center, high = hz_points[i], hz_points[i + 1], hz_points[i + 2]
        for j, freq in enumerate(fft_freqs):
            if low <= freq <= center:
                filterbank[i, j] = (freq - low) / max(center - low, 1e-10)
            elif center < freq <= high:
                filterbank[i, j] = (high - freq) / max(high - center, 1e-10)

    mel = power_spec @ filterbank.T
    mel = np.log(np.clip(mel, 1e-5, None))

    return mel.T[np.newaxis, :, :].astype(np.float32)


def _decode_rmvpe_output(output: np.ndarray) -> np.ndarray:
    """Decode RMVPE sigmoid output [1, time, 360] to F0 in Hz."""
    output = output.squeeze(0)
    pitch_hz = np.zeros(output.shape[0], dtype=np.float32)

    for i, frame in enumerate(output):
        if np.max(frame) < 0.3:
            continue
        center = np.argmax(frame)
        start = max(0, center - 4)
        end = min(360, center + 5)
        weights = frame[start:end]
        cents = RMVPE_CENTS_MAPPING[start:end]
        if np.sum(weights) > 0:
            weighted_cents = np.sum(cents * weights) / np.sum(weights)
            pitch_hz[i] = 10.0 * 2 ** (weighted_cents / 1200.0)

    return pitch_hz


def _f0_hz_to_coarse(f0_hz: np.ndarray) -> np.ndarray:
    """Convert F0 Hz to mel-encoded coarse bins (0-255) for RVC model input."""
    f0_mel = 1127.0 * np.log(1.0 + f0_hz / 700.0)
    f0_mel[f0_mel > 0] = (
        (f0_mel[f0_mel > 0] - F0_MEL_MIN) * 254.0 / (F0_MEL_MAX - F0_MEL_MIN) + 1.0
    )
    f0_mel[f0_mel <= 1] = 1
    f0_mel[f0_mel > 255] = 255
    return np.rint(f0_mel).astype(np.int64)


class RVCEngine:
    """RVC voice conversion using ONNX Runtime.

    Loads three ONNX models:
    - HuBERT: audio → 768d features (then 2x repeated for RVC)
    - RMVPE: audio → pitch (F0) in Hz
    - RVC: features + pitch → converted audio
    """

    def __init__(
        self,
        model_path: str,
        index_path: str | None = None,
        hubert_path: str | None = None,
        rmvpe_path: str | None = None,
        index_influence: float = 0.8,
        model_sr: int = 40000,
    ) -> None:
        self.model_path = model_path
        self.index_path = index_path
        self.hubert_path = hubert_path
        self.rmvpe_path = rmvpe_path
        self.index_influence = index_influence
        self.model_sr = model_sr

        self._rvc_session = None
        self._hubert_session = None
        self._rmvpe_session = None
        self._faiss_index = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load all ONNX models and FAISS index."""
        import onnxruntime as ort

        providers = self._get_providers()
        logger.info("ONNX providers: %s", providers)

        # Thread-limited session options — prevents CPU thread explosion.
        # Default would spawn N = cpu_count() threads per session × 3 sessions.
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 2
        sess_opts.inter_op_num_threads = 1
        sess_opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        logger.info("Loading RVC ONNX model...")
        self._rvc_session = ort.InferenceSession(
            self.model_path, sess_options=sess_opts, providers=providers,
        )

        if self.hubert_path and Path(self.hubert_path).exists():
            logger.info("Loading HuBERT ONNX...")
            self._hubert_session = ort.InferenceSession(
                self.hubert_path, sess_options=sess_opts, providers=providers,
            )

        if self.rmvpe_path and Path(self.rmvpe_path).exists():
            logger.info("Loading RMVPE ONNX...")
            self._rmvpe_session = ort.InferenceSession(
                self.rmvpe_path, sess_options=sess_opts, providers=providers,
            )

        if self.index_path and Path(self.index_path).exists():
            try:
                import faiss

                self._faiss_index = faiss.read_index(self.index_path)
                try:
                    self._faiss_index.make_direct_map()
                except Exception:
                    logger.warning("FAISS direct_map not supported, index retrieval disabled")
                    self._faiss_index = None
                if self._faiss_index is not None:
                    logger.info(
                        "FAISS index loaded: %d vectors", self._faiss_index.ntotal,
                    )
            except Exception as e:
                logger.warning("FAISS index failed (continuing without): %s", e)

        self._loaded = True
        logger.info("RVC ONNX engine ready!")

    def _get_providers(self) -> list[str]:
        """Select best available ONNX Runtime execution provider."""
        import onnxruntime as ort

        available = ort.get_available_providers()
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if "DmlExecutionProvider" in available:
            return ["DmlExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def convert(
        self, audio: np.ndarray, sr: int = 40000, pitch_shift: int = 0,
    ) -> np.ndarray:
        """Convert audio to JARVIS voice.

        Args:
            audio: Input float32 numpy array.
            sr: Sample rate of input audio.
            pitch_shift: Semitones to shift pitch (0 = no change).

        Returns:
            Converted float32 numpy array at model_sr (default 40kHz).
        """
        if not self._loaded:
            self.load()

        t0 = time.perf_counter()
        org_length = len(audio)

        # Resample input to model sample rate (40kHz) for F0 extraction
        audio_model_sr = self._resample(audio, sr, self.model_sr)

        # Resample to 16kHz for HuBERT feature extraction
        audio_16k = self._resample(audio, sr, 16000)

        # HuBERT features: [1, 768, seq_len] → repeat 2x → [1, seq_len*2, 768]
        t1 = time.perf_counter()
        feats = self._extract_hubert(audio_16k)
        t_hubert = time.perf_counter() - t1

        # 2x repeat along time axis (HuBERT 50fps → RVC 100fps)
        # feats is [1, 768, seq_len] from HuBERT
        feats = np.repeat(feats, 2, axis=2)  # [1, 768, seq_len*2]
        feats = feats.transpose(0, 2, 1)  # [1, seq_len*2, 768]
        hubert_length = feats.shape[1]

        # RMVPE pitch on model-sr audio, then encode for RVC
        t2 = time.perf_counter()
        pitch, pitchf = self._extract_pitch(
            audio_16k, hubert_length, pitch_shift,
        )
        t_pitch = time.perf_counter() - t2

        # FAISS index retrieval
        if self._faiss_index is not None and self.index_influence > 0:
            feats = self._apply_index(feats)

        # RVC synthesis
        t3 = time.perf_counter()
        output = self._run_rvc(feats, hubert_length, pitch, pitchf)
        t_rvc = time.perf_counter() - t3

        total = time.perf_counter() - t0

        # Trim to original length (resampled to model_sr)
        target_len = int(org_length * self.model_sr / sr)
        if len(output) > target_len:
            output = output[:target_len]

        logger.info(
            "RVC ONNX: HuBERT=%.2fs RMVPE=%.2fs RVC=%.2fs total=%.2fs (%.1fs audio)",
            t_hubert, t_pitch, t_rvc, total, len(output) / self.model_sr,
        )

        return output.astype(np.float32)

    def _resample(self, audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
        """Resample audio via linear interpolation."""
        if sr_from == sr_to:
            return audio
        new_len = int(len(audio) * sr_to / sr_from)
        return np.interp(
            np.linspace(0, len(audio) - 1, new_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    def _extract_hubert(self, audio_16k: np.ndarray) -> np.ndarray:
        """Extract HuBERT features. Returns [1, 768, seq_len] (transposed)."""
        if self._hubert_session is None:
            raise RuntimeError("HuBERT model not loaded")

        # HuBERT expects [1, 1, samples]
        input_data = audio_16k.reshape(1, 1, -1).astype(np.float32)
        input_name = self._hubert_session.get_inputs()[0].name
        outputs = self._hubert_session.run(None, {input_name: input_data})
        logits = outputs[0]  # [1, seq_len, 768]
        return logits.transpose(0, 2, 1)  # [1, 768, seq_len]

    def _extract_pitch(
        self,
        audio_16k: np.ndarray,
        target_len: int,
        pitch_shift: int = 0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Extract pitch using RMVPE, encode to mel bins for RVC.

        Returns (pitch_coarse [1, target_len], pitchf [1, target_len]).
        """
        if self._rmvpe_session is None:
            return (
                np.ones((1, target_len), dtype=np.int64),
                np.zeros((1, target_len), dtype=np.float32),
            )

        # Compute mel spectrogram for RMVPE
        mel = _mel_spectrogram(audio_16k, sr=16000)

        # Pad time dim to nearest multiple of 64 (UNet requirement)
        time_dim = mel.shape[2]
        pad_to = ((time_dim + 63) // 64) * 64
        if pad_to > time_dim:
            mel = np.pad(mel, ((0, 0), (0, 0), (0, pad_to - time_dim)))

        outputs = self._rmvpe_session.run(None, {"input": mel})
        pitch_hz = _decode_rmvpe_output(outputs[0])  # [time]

        if pitch_shift != 0:
            voiced = pitch_hz > 0
            pitch_hz[voiced] = pitch_hz[voiced] * (2 ** (pitch_shift / 12))

        # Interpolate to target length (matching hubert 2x-repeated features)
        if len(pitch_hz) != target_len:
            pitch_hz = np.interp(
                np.linspace(0, len(pitch_hz) - 1, target_len),
                np.arange(len(pitch_hz)),
                pitch_hz,
            ).astype(np.float32)

        # Encode: Hz → mel → coarse bins (0-255) for pitch input
        pitch_coarse = _f0_hz_to_coarse(pitch_hz)

        pitchf = pitch_hz.reshape(1, -1).astype(np.float32)
        pitch_coarse = pitch_coarse.reshape(1, -1)

        return pitch_coarse, pitchf

    def _apply_index(self, feats: np.ndarray) -> np.ndarray:
        """Apply FAISS index retrieval for voice timbre matching."""
        if self._faiss_index is None:
            return feats

        # feats: [1, seq_len, 768]
        feat_2d = feats.reshape(-1, feats.shape[-1]).astype(np.float32)
        _, indices = self._faiss_index.search(feat_2d, 1)

        retrieved = np.array(
            [self._faiss_index.reconstruct(int(idx)) for idx in indices[:, 0]],
        )

        alpha = self.index_influence
        blended = feat_2d * (1 - alpha) + retrieved * alpha
        return blended.reshape(feats.shape).astype(np.float32)

    def _run_rvc(
        self,
        feats: np.ndarray,
        hubert_length: int,
        pitch: np.ndarray,
        pitchf: np.ndarray,
    ) -> np.ndarray:
        """Run RVC ONNX model."""
        if self._rvc_session is None:
            raise RuntimeError("RVC model not loaded")

        ds = np.array([0], dtype=np.int64)
        rnd = np.random.randn(1, 192, hubert_length).astype(np.float32)
        hubert_length_arr = np.array([hubert_length], dtype=np.int64)

        outputs = self._rvc_session.run(
            None,
            {
                "phone": feats.astype(np.float32),
                "phone_lengths": hubert_length_arr,
                "pitch": pitch,
                "pitchf": pitchf,
                "ds": ds,
                "rnd": rnd,
            },
        )

        return outputs[0].squeeze()
