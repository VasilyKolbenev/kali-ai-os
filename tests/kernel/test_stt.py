"""Tests for Speech-to-Text."""

from types import SimpleNamespace

import numpy as np

from kernel.voice.stt import SpeechToText, STTResult


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


def _stub_stt(text: str) -> SpeechToText:
    """An STT whose model yields a single segment with the given text."""
    stt = SpeechToText()
    info = SimpleNamespace(language="ru", language_probability=0.99)

    def fake_transcribe(audio, **kwargs):  # type: ignore[no-untyped-def]
        return [_FakeSegment(text)], info

    stt._model = SimpleNamespace(transcribe=fake_transcribe)
    return stt


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


class TestHallucinationFilter:
    def test_valid_utterance_with_common_word_is_kept(self) -> None:
        """A real command merely CONTAINING 'редактору' must not be blanked."""
        stt = _stub_stt("напомни позвонить редактору")
        audio = np.zeros(16000, dtype=np.float32)
        result = stt.transcribe(audio)
        assert result.text == "напомни позвонить редактору"

    def test_real_hallucination_is_dropped(self) -> None:
        """A YouTube-style hallucination phrase is still dropped to empty."""
        stt = _stub_stt("Субтитры сделал DimaTorzok")
        audio = np.zeros(16000, dtype=np.float32)
        result = stt.transcribe(audio)
        assert result.is_empty
