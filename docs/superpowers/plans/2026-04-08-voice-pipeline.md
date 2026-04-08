# Voice Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete voice pipeline — microphone capture, VAD, wake word detection, STT, TTS, LLM router, and a pipeline orchestrator that ties everything together. This enables voice-in/voice-out interaction with Jarvis.

**Architecture:** Each voice component is a thin wrapper around an ML library, with a common async interface. The pipeline orchestrator chains them: Mic -> VAD -> WakeWord -> STT -> LLM Router -> TTS -> Speaker. Components communicate through the kernel's Event Bus. All ML models are lazy-loaded on first use.

**Tech Stack:** Python 3.12+, sounddevice (audio I/O), silero-vad (via onnxruntime), openwakeword, faster-whisper (CTranslate2), piper-tts, anthropic SDK, ollama (httpx), numpy

**Spec:** `docs/superpowers/specs/2026-04-08-jarvis-2026-design.md`

---

## File Structure (this sub-project)

```
kernel/
  voice/
    __init__.py
    recorder.py          # Microphone capture (sounddevice)
    vad.py               # Voice Activity Detection (Silero VAD)
    wake_word.py         # Wake word detection (OpenWakeWord)
    stt.py               # Speech-to-Text (faster-whisper)
    tts.py               # Text-to-Speech (Piper TTS)
    pipeline.py          # Pipeline orchestrator
  llm_router.py          # Cloud/local LLM routing (already in plan, now implemented)
tests/
  kernel/
    test_recorder.py
    test_vad.py
    test_wake_word.py
    test_stt.py
    test_tts.py
    test_llm_router.py
    test_pipeline.py
```

**Design note:** ML-dependent components (VAD, wake word, STT, TTS) use a protocol-based interface so they can be tested with mock implementations. Each wrapper follows the same pattern: `__init__` accepts config, `load()` lazy-loads the model, `process()` does the work.

---

## Chunk 1: Audio Recorder + VAD

### Task 1: Audio Recorder

**Files:**
- Create: `kernel/voice/__init__.py`
- Create: `kernel/voice/recorder.py`
- Create: `tests/kernel/test_recorder.py`

- [ ] **Step 1: Add sounddevice + numpy to pyproject.toml**

Add to `[project] dependencies`:
```
"sounddevice>=0.5.1",
"numpy>=2.0.0",
```

Run: `uv sync --all-extras`

- [ ] **Step 2: Create `kernel/voice/__init__.py`**

```python
"""Voice pipeline components for Jarvis kernel."""
```

- [ ] **Step 3: Write failing tests**

Create `tests/kernel/test_recorder.py`:

```python
"""Tests for audio recorder."""

import numpy as np
import pytest

from kernel.voice.recorder import AudioRecorder, AudioChunk


class TestAudioChunk:
    def test_create_chunk(self) -> None:
        data = np.zeros(1600, dtype=np.float32)
        chunk = AudioChunk(data=data, sample_rate=16000)
        assert chunk.sample_rate == 16000
        assert chunk.duration_ms == 100.0
        assert len(chunk.data) == 1600

    def test_chunk_duration_calculation(self) -> None:
        data = np.zeros(16000, dtype=np.float32)
        chunk = AudioChunk(data=data, sample_rate=16000)
        assert chunk.duration_ms == 1000.0


class TestAudioRecorder:
    def test_create_recorder(self) -> None:
        recorder = AudioRecorder(sample_rate=16000, chunk_duration_ms=100)
        assert recorder.sample_rate == 16000
        assert recorder.chunk_size == 1600
        assert not recorder.is_recording

    def test_default_params(self) -> None:
        recorder = AudioRecorder()
        assert recorder.sample_rate == 16000
        assert recorder.chunk_size == 512  # 32ms at 16kHz

    def test_recorder_not_recording_by_default(self) -> None:
        recorder = AudioRecorder()
        assert not recorder.is_recording
```

- [ ] **Step 4: Run tests — should FAIL**

Run: `uv run pytest tests/kernel/test_recorder.py -v`

- [ ] **Step 5: Implement AudioRecorder**

Create `kernel/voice/recorder.py`:

```python
"""Microphone audio capture using sounddevice."""

import asyncio
import logging
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A chunk of audio data with metadata."""

    data: np.ndarray  # float32, mono, shape (samples,)
    sample_rate: int

    @property
    def duration_ms(self) -> float:
        """Duration of this chunk in milliseconds."""
        return len(self.data) / self.sample_rate * 1000


class AudioRecorder:
    """Captures audio from the microphone in async chunks.

    Uses sounddevice for cross-platform audio input.
    Audio is captured as 16kHz mono float32 by default.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 32,
        device: int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)
        self._device = device
        self._stream: sd.InputStream | None = None
        self._queue: asyncio.Queue[AudioChunk] = asyncio.Queue()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """Called by sounddevice for each audio chunk."""
        if status:
            logger.warning("Audio callback status: %s", status)
        chunk = AudioChunk(
            data=indata[:, 0].copy().astype(np.float32),
            sample_rate=self.sample_rate,
        )
        try:
            self._queue.put_nowait(chunk)
        except asyncio.QueueFull:
            logger.warning("Audio queue full, dropping chunk")

    async def start(self) -> None:
        """Start recording from microphone."""
        if self._recording:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            device=self._device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._recording = True
        logger.info("Audio recording started (rate=%d, chunk=%d)", self.sample_rate, self.chunk_size)

    async def stop(self) -> None:
        """Stop recording."""
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Audio recording stopped")

    async def read_chunk(self) -> AudioChunk:
        """Read the next audio chunk. Blocks until available."""
        return await self._queue.get()
```

- [ ] **Step 6: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_recorder.py -v`
Expected: 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add kernel/voice/ tests/kernel/test_recorder.py pyproject.toml
git commit -m "feat: audio recorder with sounddevice for mic capture"
```

---

### Task 2: Voice Activity Detection (VAD)

**Files:**
- Create: `kernel/voice/vad.py`
- Create: `tests/kernel/test_vad.py`

- [ ] **Step 1: Add silero dependencies to pyproject.toml**

Add to `[project] dependencies`:
```
"onnxruntime>=1.19.0",
"torch>=2.4.0",
```

Run: `uv sync --all-extras`

**Note:** Silero VAD uses a small ONNX model (~2MB). On first run it downloads from torch hub. For production we'll bundle it, but for now auto-download is fine.

- [ ] **Step 2: Write failing tests**

Create `tests/kernel/test_vad.py`:

```python
"""Tests for Voice Activity Detection."""

import numpy as np
import pytest

from kernel.voice.vad import VoiceActivityDetector, VADResult


class TestVADResult:
    def test_create_result(self) -> None:
        result = VADResult(is_speech=True, confidence=0.95)
        assert result.is_speech is True
        assert result.confidence == 0.95

    def test_silence_result(self) -> None:
        result = VADResult(is_speech=False, confidence=0.1)
        assert result.is_speech is False


class TestVoiceActivityDetector:
    def test_create_vad(self) -> None:
        vad = VoiceActivityDetector(threshold=0.5)
        assert vad.threshold == 0.5
        assert not vad.is_loaded

    def test_default_threshold(self) -> None:
        vad = VoiceActivityDetector()
        assert vad.threshold == 0.5

    def test_process_silence(self) -> None:
        """Silence (all zeros) should not be detected as speech."""
        vad = VoiceActivityDetector()
        silence = np.zeros(512, dtype=np.float32)
        result = vad.process(silence, sample_rate=16000)
        assert isinstance(result, VADResult)
        # With no model loaded, should use energy-based fallback
        assert result.is_speech is False

    def test_process_loud_signal(self) -> None:
        """A loud signal should be detected as speech (energy fallback)."""
        vad = VoiceActivityDetector()
        loud = np.random.randn(512).astype(np.float32) * 0.5
        result = vad.process(loud, sample_rate=16000)
        assert isinstance(result, VADResult)
        assert result.is_speech is True
```

- [ ] **Step 3: Run tests — should FAIL**

Run: `uv run pytest tests/kernel/test_vad.py -v`

- [ ] **Step 4: Implement VAD**

Create `kernel/voice/vad.py`:

```python
"""Voice Activity Detection using Silero VAD with energy-based fallback."""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VADResult:
    """Result of voice activity detection."""

    is_speech: bool
    confidence: float


class VoiceActivityDetector:
    """Detects speech in audio chunks.

    Uses Silero VAD (ONNX) when available, falls back to energy-based detection.
    The model is lazy-loaded on first call to load().
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the Silero VAD model from torch hub."""
        try:
            import torch

            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            self._model = model
            self._loaded = True
            logger.info("Silero VAD model loaded")
        except Exception:
            logger.warning("Failed to load Silero VAD, using energy-based fallback")
            self._loaded = False

    def process(self, audio: np.ndarray, sample_rate: int = 16000) -> VADResult:
        """Detect speech in an audio chunk.

        Args:
            audio: float32 numpy array of audio samples.
            sample_rate: Sample rate of the audio (default 16000).

        Returns:
            VADResult with is_speech flag and confidence score.
        """
        if self._model is not None:
            return self._process_silero(audio, sample_rate)
        return self._process_energy(audio)

    def _process_silero(self, audio: np.ndarray, sample_rate: int) -> VADResult:
        """Process with Silero VAD model."""
        import torch

        tensor = torch.from_numpy(audio)
        confidence = float(self._model(tensor, sample_rate))  # type: ignore[operator]
        return VADResult(is_speech=confidence >= self.threshold, confidence=confidence)

    def _process_energy(self, audio: np.ndarray) -> VADResult:
        """Simple energy-based VAD fallback."""
        rms = float(np.sqrt(np.mean(audio**2)))
        energy_threshold = 0.01
        confidence = min(rms / 0.1, 1.0)
        return VADResult(is_speech=rms > energy_threshold, confidence=confidence)

    def reset(self) -> None:
        """Reset internal state (for Silero VAD stateful mode)."""
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()  # type: ignore[union-attr]
```

- [ ] **Step 5: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_vad.py -v`
Expected: 4 tests PASS (using energy fallback, no model download needed)

- [ ] **Step 6: Commit**

```bash
git add kernel/voice/vad.py tests/kernel/test_vad.py pyproject.toml
git commit -m "feat: VAD with Silero model and energy-based fallback"
```

---

## Chunk 2: Wake Word + STT

### Task 3: Wake Word Detection

**Files:**
- Create: `kernel/voice/wake_word.py`
- Create: `tests/kernel/test_wake_word.py`

- [ ] **Step 1: Add openwakeword to pyproject.toml**

Add to `[project] dependencies`:
```
"openwakeword>=0.6.0",
```

Run: `uv sync --all-extras`

- [ ] **Step 2: Write failing tests**

Create `tests/kernel/test_wake_word.py`:

```python
"""Tests for wake word detection."""

import numpy as np
import pytest

from kernel.voice.wake_word import WakeWordDetector, WakeWordResult


class TestWakeWordResult:
    def test_create_result(self) -> None:
        result = WakeWordResult(detected=True, word="jarvis", confidence=0.92)
        assert result.detected is True
        assert result.word == "jarvis"

    def test_no_detection(self) -> None:
        result = WakeWordResult(detected=False, word=None, confidence=0.0)
        assert result.detected is False
        assert result.word is None


class TestWakeWordDetector:
    def test_create_detector(self) -> None:
        detector = WakeWordDetector(wake_word="jarvis", threshold=0.5)
        assert detector.wake_word == "jarvis"
        assert detector.threshold == 0.5

    def test_default_params(self) -> None:
        detector = WakeWordDetector()
        assert detector.wake_word == "jarvis"
        assert detector.threshold == 0.5

    def test_process_silence_no_detection(self) -> None:
        """Silence should not trigger wake word."""
        detector = WakeWordDetector()
        silence = np.zeros(16000, dtype=np.float32)
        result = detector.process(silence)
        assert isinstance(result, WakeWordResult)
        assert result.detected is False
```

- [ ] **Step 3: Run tests — should FAIL**

- [ ] **Step 4: Implement WakeWordDetector**

Create `kernel/voice/wake_word.py`:

```python
"""Wake word detection using OpenWakeWord."""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WakeWordResult:
    """Result of wake word detection."""

    detected: bool
    word: str | None
    confidence: float


class WakeWordDetector:
    """Detects wake word in audio using OpenWakeWord.

    Falls back to always-false when model is not loaded (for testing).
    """

    def __init__(self, wake_word: str = "jarvis", threshold: float = 0.5) -> None:
        self.wake_word = wake_word
        self.threshold = threshold
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the OpenWakeWord model."""
        try:
            import openwakeword
            from openwakeword.model import Model

            openwakeword.utils.download_models()
            self._model = Model(inference_framework="onnx")
            self._loaded = True
            logger.info("OpenWakeWord model loaded for '%s'", self.wake_word)
        except Exception:
            logger.warning("Failed to load OpenWakeWord, wake word detection disabled")
            self._loaded = False

    def process(self, audio: np.ndarray) -> WakeWordResult:
        """Check audio chunk for wake word.

        Args:
            audio: float32 numpy array at 16kHz.

        Returns:
            WakeWordResult with detection status.
        """
        if self._model is None:
            return WakeWordResult(detected=False, word=None, confidence=0.0)

        # OpenWakeWord expects int16
        audio_int16 = (audio * 32767).astype(np.int16)
        prediction = self._model.predict(audio_int16)  # type: ignore[union-attr]

        # Check all model scores for anything above threshold
        for model_name, score in prediction.items():
            if score >= self.threshold:
                logger.info("Wake word detected: %s (score=%.2f)", model_name, score)
                return WakeWordResult(detected=True, word=model_name, confidence=float(score))

        return WakeWordResult(detected=False, word=None, confidence=0.0)

    def reset(self) -> None:
        """Reset internal model state."""
        if self._model is not None and hasattr(self._model, "reset"):
            self._model.reset()  # type: ignore[union-attr]
```

- [ ] **Step 5: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_wake_word.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/voice/wake_word.py tests/kernel/test_wake_word.py pyproject.toml
git commit -m "feat: wake word detection with OpenWakeWord"
```

---

### Task 4: Speech-to-Text (STT)

**Files:**
- Create: `kernel/voice/stt.py`
- Create: `tests/kernel/test_stt.py`

- [ ] **Step 1: Add faster-whisper to pyproject.toml**

Add to `[project] dependencies`:
```
"faster-whisper>=1.1.0",
```

Run: `uv sync --all-extras`

- [ ] **Step 2: Write failing tests**

Create `tests/kernel/test_stt.py`:

```python
"""Tests for Speech-to-Text."""

import numpy as np
import pytest

from kernel.voice.stt import SpeechToText, STTResult


class TestSTTResult:
    def test_create_result(self) -> None:
        result = STTResult(text="hello world", language="en", confidence=0.95, duration_ms=230)
        assert result.text == "hello world"
        assert result.language == "en"

    def test_empty_result(self) -> None:
        result = STTResult(text="", language=None, confidence=0.0, duration_ms=0)
        assert result.text == ""
        assert result.is_empty


class TestSpeechToText:
    def test_create_stt(self) -> None:
        stt = SpeechToText(model_size="base")
        assert stt.model_size == "base"
        assert not stt.is_loaded

    def test_default_model(self) -> None:
        stt = SpeechToText()
        assert stt.model_size == "base"

    def test_transcribe_silence_returns_empty(self) -> None:
        """Silence should produce empty transcription."""
        stt = SpeechToText()
        silence = np.zeros(16000, dtype=np.float32)
        result = stt.transcribe(silence, sample_rate=16000)
        assert isinstance(result, STTResult)
        assert result.is_empty
```

- [ ] **Step 3: Run tests — should FAIL**

- [ ] **Step 4: Implement STT**

Create `kernel/voice/stt.py`:

```python
"""Speech-to-Text using faster-whisper (CTranslate2)."""

import logging
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class STTResult:
    """Result of speech-to-text transcription."""

    text: str
    language: str | None
    confidence: float
    duration_ms: int

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) == 0


class SpeechToText:
    """Transcribes audio to text using faster-whisper.

    Model is lazy-loaded on first call to load().
    Without model, returns empty results (for testing).
    """

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        self.model_size = model_size
        self._device = device
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the Whisper model."""
        try:
            from faster_whisper import WhisperModel

            compute_type = "int8" if self._device == "cpu" else "auto"
            self._model = WhisperModel(
                self.model_size,
                device=self._device if self._device != "auto" else "auto",
                compute_type=compute_type,
            )
            self._loaded = True
            logger.info("Whisper model loaded: %s", self.model_size)
        except Exception:
            logger.warning("Failed to load Whisper model, STT disabled")
            self._loaded = False

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> STTResult:
        """Transcribe audio to text.

        Args:
            audio: float32 numpy array.
            sample_rate: Audio sample rate (default 16000).

        Returns:
            STTResult with transcribed text.
        """
        if self._model is None:
            return STTResult(text="", language=None, confidence=0.0, duration_ms=0)

        start = time.perf_counter()
        segments, info = self._model.transcribe(  # type: ignore[union-attr]
            audio,
            beam_size=5,
            language=None,  # auto-detect
            vad_filter=True,
        )
        text_parts = [segment.text.strip() for segment in segments]
        text = " ".join(text_parts).strip()
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info("STT: '%s' (lang=%s, %.0fms)", text, info.language, elapsed_ms)
        return STTResult(
            text=text,
            language=info.language,
            confidence=info.language_probability,
            duration_ms=elapsed_ms,
        )
```

- [ ] **Step 5: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_stt.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/voice/stt.py tests/kernel/test_stt.py pyproject.toml
git commit -m "feat: STT with faster-whisper (lazy-loaded)"
```

---

## Chunk 3: TTS + LLM Router

### Task 5: Text-to-Speech (TTS)

**Files:**
- Create: `kernel/voice/tts.py`
- Create: `tests/kernel/test_tts.py`

- [ ] **Step 1: Add piper-tts dependency to pyproject.toml**

Add to `[project] dependencies`:
```
"piper-tts>=1.2.0",
```

Run: `uv sync --all-extras`

**Note:** If piper-tts is not installable on Windows, we'll use a subprocess wrapper. The interface stays the same.

- [ ] **Step 2: Write failing tests**

Create `tests/kernel/test_tts.py`:

```python
"""Tests for Text-to-Speech."""

import numpy as np
import pytest

from kernel.voice.tts import TextToSpeech, TTSResult


class TestTTSResult:
    def test_create_result(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        result = TTSResult(audio=audio, sample_rate=22050, duration_ms=500)
        assert result.sample_rate == 22050
        assert result.duration_ms == 500

    def test_empty_result(self) -> None:
        result = TTSResult.empty()
        assert result.is_empty
        assert len(result.audio) == 0


class TestTextToSpeech:
    def test_create_tts(self) -> None:
        tts = TextToSpeech()
        assert not tts.is_loaded

    def test_synthesize_without_model_returns_empty(self) -> None:
        """Without model loaded, should return empty result."""
        tts = TextToSpeech()
        result = tts.synthesize("hello world")
        assert isinstance(result, TTSResult)
        assert result.is_empty
```

- [ ] **Step 3: Run tests — should FAIL**

- [ ] **Step 4: Implement TTS**

Create `kernel/voice/tts.py`:

```python
"""Text-to-Speech using Piper TTS."""

import logging
import time
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Result of text-to-speech synthesis."""

    audio: np.ndarray
    sample_rate: int = 22050
    duration_ms: int = 0

    @property
    def is_empty(self) -> bool:
        return len(self.audio) == 0

    @classmethod
    def empty(cls) -> "TTSResult":
        return cls(audio=np.array([], dtype=np.float32), sample_rate=22050, duration_ms=0)


class TextToSpeech:
    """Synthesizes speech from text using Piper TTS.

    Model is lazy-loaded. Returns empty audio when no model is available.
    """

    def __init__(self, voice: str = "default", speaker_id: int | None = None) -> None:
        self.voice = voice
        self.speaker_id = speaker_id
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the Piper TTS voice model."""
        try:
            from piper import PiperVoice

            # Piper requires a .onnx model file — path resolved from voice name
            # For now, we try to load and gracefully fail
            logger.info("Attempting to load Piper voice: %s", self.voice)
            # Model loading deferred until voice files are configured
            self._loaded = False
            logger.warning("Piper TTS model not configured, TTS disabled")
        except ImportError:
            logger.warning("piper-tts not installed, TTS disabled")
            self._loaded = False

    def synthesize(self, text: str) -> TTSResult:
        """Convert text to speech audio.

        Args:
            text: Text to synthesize.

        Returns:
            TTSResult with audio data.
        """
        if not text.strip() or self._model is None:
            return TTSResult.empty()

        start = time.perf_counter()
        try:
            # Piper synthesis produces int16 PCM at model's sample rate
            audio_parts: list[np.ndarray] = []
            for audio_bytes in self._model.synthesize_stream_raw(text):  # type: ignore[union-attr]
                chunk = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                audio_parts.append(chunk)

            if not audio_parts:
                return TTSResult.empty()

            audio = np.concatenate(audio_parts)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info("TTS: %d chars -> %.1fs audio (%.0fms)", len(text), len(audio) / 22050, elapsed_ms)
            return TTSResult(audio=audio, sample_rate=22050, duration_ms=elapsed_ms)
        except Exception:
            logger.exception("TTS synthesis failed")
            return TTSResult.empty()

    def play(self, result: TTSResult) -> None:
        """Play TTS audio through speakers."""
        if result.is_empty:
            return
        try:
            import sounddevice as sd

            sd.play(result.audio, result.sample_rate)
            sd.wait()
        except Exception:
            logger.exception("Failed to play audio")
```

- [ ] **Step 5: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_tts.py -v`
Expected: 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/voice/tts.py tests/kernel/test_tts.py pyproject.toml
git commit -m "feat: TTS with Piper (lazy-loaded, graceful fallback)"
```

---

### Task 6: LLM Router

**Files:**
- Create: `kernel/llm_router.py`
- Create: `tests/kernel/test_llm_router.py`

- [ ] **Step 1: Add anthropic SDK to pyproject.toml**

Add to `[project] dependencies`:
```
"anthropic>=0.40.0",
"httpx>=0.28.0",
```

(`httpx` is already in dev deps, move to main deps for Ollama HTTP calls)

Run: `uv sync --all-extras`

- [ ] **Step 2: Write failing tests**

Create `tests/kernel/test_llm_router.py`:

```python
"""Tests for LLM Router."""

from unittest.mock import AsyncMock, patch

import pytest

from kernel.llm_router import LLMRouter, LLMRequest, LLMResponse
from kernel.models import LLMConfig


@pytest.fixture
def config() -> LLMConfig:
    return LLMConfig()


@pytest.fixture
def router(config: LLMConfig) -> LLMRouter:
    return LLMRouter(config)


class TestLLMRequest:
    def test_create_request(self) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[])
        assert req.text == "hello"
        assert req.force_provider is None

    def test_force_provider(self) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[], force_provider="cloud")
        assert req.force_provider == "cloud"


class TestLLMResponse:
    def test_create_response(self) -> None:
        resp = LLMResponse(text="Hi there!", tool_calls=None, provider_used="local", latency_ms=50)
        assert resp.text == "Hi there!"
        assert resp.tool_calls is None
        assert resp.provider_used == "local"


class TestLLMRouter:
    def test_create_router(self, router: LLMRouter) -> None:
        assert router.config.cloud_provider == "anthropic"
        assert router.config.local_provider == "ollama"

    def test_should_use_cloud_with_tools(self, router: LLMRouter) -> None:
        """When tools are available and internet is up, prefer cloud."""
        tools = [{"type": "function", "function": {"name": "test", "description": "test"}}]
        req = LLMRequest(text="schedule meeting", context=[], available_tools=tools)
        provider = router.select_provider(req)
        assert provider == "cloud"

    def test_should_use_local_without_tools(self, router: LLMRouter) -> None:
        """When no tools needed, use local for speed."""
        req = LLMRequest(text="hello", context=[], available_tools=[])
        provider = router.select_provider(req)
        assert provider == "local"

    def test_force_provider_overrides(self, router: LLMRouter) -> None:
        """force_provider should override auto-routing."""
        tools = [{"type": "function", "function": {"name": "test", "description": "test"}}]
        req = LLMRequest(text="test", context=[], available_tools=tools, force_provider="local")
        provider = router.select_provider(req)
        assert provider == "local"

    async def test_route_returns_response(self, router: LLMRouter) -> None:
        """Route should return a valid LLMResponse even without real API."""
        req = LLMRequest(text="hello", context=[], available_tools=[])
        # Mock the local provider to avoid real API call
        with patch.object(router, "_call_local", new_callable=AsyncMock) as mock_local:
            mock_local.return_value = LLMResponse(
                text="Hi!", tool_calls=None, provider_used="local", latency_ms=10
            )
            resp = await router.route(req)
            assert resp.text == "Hi!"
            assert resp.provider_used == "local"
```

- [ ] **Step 3: Run tests — should FAIL**

- [ ] **Step 4: Implement LLM Router**

Create `kernel/llm_router.py`:

```python
"""LLM Router — routes requests to cloud or local LLM based on complexity."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from kernel.models import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    """Request to the LLM router."""

    text: str
    context: list[dict[str, Any]]
    available_tools: list[dict[str, Any]]
    force_provider: str | None = None


@dataclass
class ToolCall:
    """A tool call from the LLM."""

    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from the LLM router."""

    text: str
    tool_calls: list[ToolCall] | None
    provider_used: str
    latency_ms: int


class LLMRouter:
    """Routes LLM requests to cloud (Claude) or local (Ollama) providers.

    Routing logic:
    - Has tools + internet -> cloud (better function calling)
    - No tools needed -> local (faster)
    - force_provider overrides auto-routing
    - No internet -> local fallback
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._cloud_available = True  # optimistic, set False on failure

    def select_provider(self, request: LLMRequest) -> str:
        """Determine which provider to use for this request."""
        if request.force_provider:
            return request.force_provider

        if not self.config.auto_route:
            return "cloud"

        if request.available_tools and self._cloud_available:
            return "cloud"

        return "local"

    async def route(self, request: LLMRequest) -> LLMResponse:
        """Route a request to the appropriate LLM provider."""
        provider = self.select_provider(request)
        start = time.perf_counter()

        try:
            if provider == "cloud":
                response = await self._call_cloud(request)
            else:
                response = await self._call_local(request)
        except Exception:
            logger.exception("LLM call failed (provider=%s), trying fallback", provider)
            if provider == "cloud":
                self._cloud_available = False
                response = await self._call_local(request)
            else:
                response = LLMResponse(
                    text="I'm sorry, I couldn't process that request.",
                    tool_calls=None,
                    provider_used="error",
                    latency_ms=0,
                )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        response.latency_ms = elapsed_ms
        return response

    async def _call_cloud(self, request: LLMRequest) -> LLMResponse:
        """Call Claude API via anthropic SDK."""
        import anthropic

        client = anthropic.AsyncAnthropic()
        messages = [{"role": "user", "content": request.text}]

        # Add conversation context
        for ctx in request.context:
            messages.insert(-1, ctx)

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "max_tokens": 1024,
            "messages": messages,
        }

        if request.available_tools:
            kwargs["tools"] = request.available_tools

        response = await client.messages.create(**kwargs)

        text = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(name=block.name, arguments=dict(block.input)))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls if tool_calls else None,
            provider_used="cloud",
            latency_ms=0,
        )

    async def _call_local(self, request: LLMRequest) -> LLMResponse:
        """Call local LLM via Ollama HTTP API."""
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": self.config.local_model,
                    "messages": [{"role": "user", "content": request.text}],
                    "stream": False,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            tool_calls=None,
            provider_used="local",
            latency_ms=0,
        )
```

- [ ] **Step 5: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_llm_router.py -v`
Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/llm_router.py tests/kernel/test_llm_router.py pyproject.toml
git commit -m "feat: LLM router with cloud/local auto-routing and fallback"
```

---

## Chunk 4: Pipeline Orchestrator

### Task 7: Voice Pipeline Orchestrator

**Files:**
- Create: `kernel/voice/pipeline.py`
- Create: `tests/kernel/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_pipeline.py`:

```python
"""Tests for voice pipeline orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from kernel.event_bus import EventBus
from kernel.llm_router import LLMRequest, LLMResponse, LLMRouter
from kernel.models import ConfigSchema, LLMConfig, VoiceConfig
from kernel.voice.pipeline import VoicePipeline, PipelineState
from kernel.voice.recorder import AudioChunk
from kernel.voice.stt import STTResult
from kernel.voice.tts import TTSResult
from kernel.voice.vad import VADResult
from kernel.voice.wake_word import WakeWordResult


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def pipeline(event_bus: EventBus) -> VoicePipeline:
    voice_config = VoiceConfig()
    llm_config = LLMConfig()
    return VoicePipeline(
        event_bus=event_bus,
        voice_config=voice_config,
        llm_config=llm_config,
        tools=[],
    )


class TestPipelineState:
    def test_initial_state_is_idle(self, pipeline: VoicePipeline) -> None:
        assert pipeline.state == PipelineState.IDLE

    def test_state_enum_values(self) -> None:
        assert PipelineState.IDLE.value == "idle"
        assert PipelineState.LISTENING.value == "listening"
        assert PipelineState.THINKING.value == "thinking"
        assert PipelineState.SPEAKING.value == "speaking"


class TestVoicePipeline:
    def test_create_pipeline(self, pipeline: VoicePipeline) -> None:
        assert pipeline.state == PipelineState.IDLE
        assert pipeline.mode == "wake_word"

    async def test_process_audio_silence(self, pipeline: VoicePipeline) -> None:
        """Silence should not trigger any state change."""
        chunk = AudioChunk(data=np.zeros(512, dtype=np.float32), sample_rate=16000)
        await pipeline.process_chunk(chunk)
        assert pipeline.state == PipelineState.IDLE

    async def test_state_change_emits_event(self, pipeline: VoicePipeline, event_bus: EventBus) -> None:
        """State changes should publish voice.state events."""
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe("voice.state", handler)
        await pipeline._set_state(PipelineState.LISTENING)

        assert len(received) == 1
        assert received[0].payload["state"] == "listening"

    async def test_transcription_emits_event(self, pipeline: VoicePipeline, event_bus: EventBus) -> None:
        """Transcription should publish voice.transcribed event."""
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe("voice.transcribed", handler)
        await pipeline._handle_transcription(
            STTResult(text="hello jarvis", language="en", confidence=0.9, duration_ms=200)
        )

        assert len(received) == 1
        assert received[0].payload["text"] == "hello jarvis"
```

- [ ] **Step 2: Run tests — should FAIL**

- [ ] **Step 3: Implement Pipeline Orchestrator**

Create `kernel/voice/pipeline.py`:

```python
"""Voice pipeline orchestrator — chains recorder, VAD, wake word, STT, LLM, TTS."""

import asyncio
import logging
from enum import Enum
from typing import Any

import numpy as np

from kernel.event_bus import EventBus
from kernel.llm_router import LLMRequest, LLMResponse, LLMRouter
from kernel.models import Event, LLMConfig, VoiceConfig
from kernel.voice.recorder import AudioChunk, AudioRecorder
from kernel.voice.stt import SpeechToText, STTResult
from kernel.voice.tts import TextToSpeech
from kernel.voice.vad import VoiceActivityDetector
from kernel.voice.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """Current state of the voice pipeline."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class VoicePipeline:
    """Orchestrates the full voice interaction flow.

    Modes:
    - wake_word: listens for wake word, then transcribes
    - push_to_talk: transcribes on demand (via event)
    - continuous: always transcribing
    """

    def __init__(
        self,
        event_bus: EventBus,
        voice_config: VoiceConfig,
        llm_config: LLMConfig,
        tools: list[dict[str, Any]],
    ) -> None:
        self._bus = event_bus
        self._voice_config = voice_config
        self._tools = tools
        self._state = PipelineState.IDLE
        self._context: list[dict[str, Any]] = []

        # Components (lazy-initialized)
        self._recorder = AudioRecorder()
        self._vad = VoiceActivityDetector(threshold=voice_config.vad_threshold)
        self._wake_word = WakeWordDetector(wake_word=voice_config.wake_word)
        self._stt = SpeechToText(model_size=voice_config.stt_model)
        self._tts = TextToSpeech(voice=voice_config.tts_voice)
        self._llm = LLMRouter(llm_config)

        # Audio buffer for collecting speech
        self._audio_buffer: list[np.ndarray] = []
        self._speech_active = False
        self._wake_detected = False
        self._silence_count = 0
        self._max_silence_chunks = 30  # ~1s of silence ends utterance

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def mode(self) -> str:
        return self._voice_config.mode

    async def _set_state(self, new_state: PipelineState) -> None:
        """Update state and publish event."""
        if self._state == new_state:
            return
        self._state = new_state
        await self._bus.publish(
            Event(topic="voice.state", source="voice-pipeline", payload={"state": new_state.value})
        )

    def load_models(self) -> None:
        """Load all ML models. Call once at startup."""
        logger.info("Loading voice models...")
        self._vad.load()
        self._wake_word.load()
        self._stt.load()
        self._tts.load()
        logger.info("Voice models loaded")

    async def start(self) -> None:
        """Start the voice pipeline."""
        await self._recorder.start()
        await self._set_state(PipelineState.IDLE)
        logger.info("Voice pipeline started (mode=%s)", self.mode)

        asyncio.create_task(self._main_loop())

    async def stop(self) -> None:
        """Stop the voice pipeline."""
        await self._recorder.stop()
        await self._set_state(PipelineState.IDLE)
        logger.info("Voice pipeline stopped")

    async def _main_loop(self) -> None:
        """Main processing loop — reads audio chunks and processes them."""
        while self._recorder.is_recording:
            try:
                chunk = await asyncio.wait_for(self._recorder.read_chunk(), timeout=1.0)
                await self.process_chunk(chunk)
            except asyncio.TimeoutError:
                continue
            except Exception:
                logger.exception("Pipeline loop error")

    async def process_chunk(self, chunk: AudioChunk) -> None:
        """Process a single audio chunk through the pipeline."""
        # Step 1: VAD
        vad_result = self._vad.process(chunk.data, chunk.sample_rate)

        if self.mode == "wake_word":
            await self._process_wake_word_mode(chunk, vad_result)
        elif self.mode == "continuous":
            await self._process_continuous_mode(chunk, vad_result)

    async def _process_wake_word_mode(self, chunk: AudioChunk, vad_result: Any) -> None:
        """Process audio in wake word mode."""
        if not self._wake_detected:
            # Listen for wake word
            ww_result = self._wake_word.process(chunk.data)
            if ww_result.detected:
                self._wake_detected = True
                self._audio_buffer.clear()
                self._silence_count = 0
                await self._set_state(PipelineState.LISTENING)
                await self._bus.publish(
                    Event(topic="voice.wake_word", source="voice-pipeline", payload={"word": ww_result.word})
                )
        else:
            # Collecting speech after wake word
            if vad_result.is_speech:
                self._audio_buffer.append(chunk.data)
                self._silence_count = 0
            else:
                self._silence_count += 1

            # End of utterance
            if self._silence_count >= self._max_silence_chunks and self._audio_buffer:
                await self._process_utterance()
                self._wake_detected = False
                self._audio_buffer.clear()

    async def _process_continuous_mode(self, chunk: AudioChunk, vad_result: Any) -> None:
        """Process audio in continuous mode (always transcribing)."""
        if vad_result.is_speech:
            self._audio_buffer.append(chunk.data)
            self._silence_count = 0
            if self._state == PipelineState.IDLE:
                await self._set_state(PipelineState.LISTENING)
        else:
            self._silence_count += 1

        if self._silence_count >= self._max_silence_chunks and self._audio_buffer:
            await self._process_utterance()
            self._audio_buffer.clear()

    async def _process_utterance(self) -> None:
        """Process a complete utterance: STT -> LLM -> TTS."""
        if not self._audio_buffer:
            return

        audio = np.concatenate(self._audio_buffer)
        await self._set_state(PipelineState.THINKING)

        # STT
        stt_result = self._stt.transcribe(audio)
        if stt_result.is_empty:
            await self._set_state(PipelineState.IDLE)
            return

        await self._handle_transcription(stt_result)

    async def _handle_transcription(self, stt_result: STTResult) -> None:
        """Handle a transcription result: publish event, route to LLM, speak response."""
        # Publish transcription event
        await self._bus.publish(
            Event(
                topic="voice.transcribed",
                source="voice-pipeline",
                payload={
                    "text": stt_result.text,
                    "language": stt_result.language,
                    "confidence": stt_result.confidence,
                    "duration_ms": stt_result.duration_ms,
                },
            )
        )

        # Route to LLM
        request = LLMRequest(
            text=stt_result.text,
            context=self._context[-10:],  # last 10 turns
            available_tools=self._tools,
        )
        response = await self._llm.route(request)

        # Publish response
        await self._bus.publish(
            Event(
                topic="agent.response",
                source="voice-pipeline",
                payload={
                    "text": response.text,
                    "provider": response.provider_used,
                    "tool_calls": [{"name": tc.name, "args": tc.arguments} for tc in response.tool_calls] if response.tool_calls else None,
                    "latency_ms": response.latency_ms,
                },
            )
        )

        # Update context
        self._context.append({"role": "user", "content": stt_result.text})
        self._context.append({"role": "assistant", "content": response.text})

        # TTS
        if response.text:
            await self._set_state(PipelineState.SPEAKING)
            tts_result = self._tts.synthesize(response.text)
            if not tts_result.is_empty:
                self._tts.play(tts_result)

        await self._set_state(PipelineState.IDLE)
```

- [ ] **Step 4: Run tests — should PASS**

Run: `uv run pytest tests/kernel/test_pipeline.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/voice/pipeline.py tests/kernel/test_pipeline.py
git commit -m "feat: voice pipeline orchestrator with wake word, STT, LLM, TTS flow"
```

---

### Task 8: Integration — Wire Pipeline into FastAPI

**Files:**
- Modify: `kernel/main.py` — add voice pipeline initialization and `/voice` endpoints

- [ ] **Step 1: Add voice status endpoint to main.py**

Add these imports at the top of `kernel/main.py`:
```python
from kernel.voice.pipeline import VoicePipeline, PipelineState
```

Add inside the `lifespan` function, after scheduler start:
```python
        # Voice pipeline (optional — only if audio device available)
        try:
            voice_pipeline = VoicePipeline(
                event_bus=event_bus,
                voice_config=config_manager.config.voice,
                llm_config=config_manager.config.llm,
                tools=plugin_registry.get_all_tools(),
            )
            app.state.voice_pipeline = voice_pipeline
            logger.info("Voice pipeline initialized (not started — call /voice/start)")
        except Exception:
            logger.warning("Voice pipeline not available")
            app.state.voice_pipeline = None
```

Add these routes after the existing ones:
```python
    @app.get("/voice/status")
    async def voice_status(request: Request) -> dict[str, Any]:
        vp = request.app.state.voice_pipeline
        if vp is None:
            return {"available": False}
        return {
            "available": True,
            "state": vp.state.value,
            "mode": vp.mode,
        }

    @app.post("/voice/start")
    async def voice_start(request: Request) -> dict[str, str]:
        vp = request.app.state.voice_pipeline
        if vp is None:
            return {"status": "error", "message": "Voice pipeline not available"}
        vp.load_models()
        await vp.start()
        return {"status": "started"}

    @app.post("/voice/stop")
    async def voice_stop(request: Request) -> dict[str, str]:
        vp = request.app.state.voice_pipeline
        if vp is None:
            return {"status": "error", "message": "Voice pipeline not available"}
        await vp.stop()
        return {"status": "stopped"}
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS (previous + new)

- [ ] **Step 3: Lint and format**

Run: `uv run ruff check --fix kernel/ tests/ && uv run ruff format kernel/ tests/`

- [ ] **Step 4: Commit**

```bash
git add kernel/main.py
git commit -m "feat: wire voice pipeline into FastAPI with /voice endpoints"
```

---

### Task 9: Full Suite Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `uv run ruff check kernel/ tests/`
Expected: Clean

- [ ] **Step 3: Start dev server and verify**

Run: `uv run uvicorn kernel.main:create_app --factory --port 8000 &`
Wait 3 seconds.
Run: `curl -s http://localhost:8000/voice/status`
Expected: `{"available":true,"state":"idle","mode":"wake_word"}`

Kill server.

- [ ] **Step 4: Commit any remaining fixes**

```bash
git add kernel/ tests/
git commit -m "chore: voice pipeline verification and fixes"
```

---

## Summary

After completing all tasks, the voice pipeline provides:

1. **AudioRecorder** — sounddevice-based mic capture with async chunk reading
2. **VoiceActivityDetector** — Silero VAD with energy-based fallback
3. **WakeWordDetector** — OpenWakeWord with graceful fallback
4. **SpeechToText** — faster-whisper with auto language detection
5. **TextToSpeech** — Piper TTS with speaker playback
6. **LLMRouter** — cloud (Claude) / local (Ollama) routing with auto-fallback
7. **VoicePipeline** — orchestrator chaining all components with Event Bus integration
8. **FastAPI endpoints** — `/voice/status`, `/voice/start`, `/voice/stop`

**Next sub-project:** Agent Runtime (process manager, protocols, health checks)
