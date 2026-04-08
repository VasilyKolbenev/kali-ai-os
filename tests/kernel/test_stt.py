"""Tests for Speech-to-Text."""

import numpy as np

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
        stt = SpeechToText()
        silence = np.zeros(16000, dtype=np.float32)
        result = stt.transcribe(silence, sample_rate=16000)
        assert isinstance(result, STTResult)
        assert result.is_empty
