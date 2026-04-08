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
        tts = TextToSpeech()
        result = tts.synthesize("hello world")
        assert isinstance(result, TTSResult)
        assert result.is_empty
