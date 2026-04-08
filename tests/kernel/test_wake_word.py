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
        detector = WakeWordDetector()
        silence = np.zeros(16000, dtype=np.float32)
        result = detector.process(silence)
        assert isinstance(result, WakeWordResult)
        assert result.detected is False
