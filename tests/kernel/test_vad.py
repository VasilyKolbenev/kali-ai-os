"""Tests for Voice Activity Detection."""

import numpy as np

from kernel.voice.vad import VADResult, VoiceActivityDetector


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
        vad = VoiceActivityDetector()
        silence = np.zeros(512, dtype=np.float32)
        result = vad.process(silence, sample_rate=16000)
        assert isinstance(result, VADResult)
        assert result.is_speech is False

    def test_process_loud_signal(self) -> None:
        vad = VoiceActivityDetector()
        loud = np.random.randn(512).astype(np.float32) * 0.5
        result = vad.process(loud, sample_rate=16000)
        assert isinstance(result, VADResult)
        assert result.is_speech is True
