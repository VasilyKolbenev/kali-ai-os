"""Latency-surgery invariants of the desktop voice pipeline (Sprint 1)."""
from kernel.event_bus import EventBus
from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import VoicePipeline


def _mk() -> VoicePipeline:
    return VoicePipeline(EventBus(), VoiceConfig(), LLMConfig(), tools=[])


def test_default_silence_window_is_900ms(monkeypatch) -> None:
    monkeypatch.delenv("KALI_SILENCE_MS", raising=False)
    p = _mk()
    assert p._max_silence_chunks == 900 // 32  # 28 chunks


def test_silence_window_env_override(monkeypatch) -> None:
    monkeypatch.setenv("KALI_SILENCE_MS", "2500")
    p = _mk()
    assert p._max_silence_chunks == 2500 // 32


async def test_stt_runs_off_the_event_loop() -> None:
    """transcribe must execute in a worker thread (to_thread contract) —
    a blocking Whisper call on the loop freezes every concurrent task."""
    import threading

    import numpy as np

    p = _mk()
    seen_thread: list[threading.Thread] = []

    def fake_transcribe(audio):
        seen_thread.append(threading.current_thread())
        from kernel.voice.stt import STTResult
        return STTResult(text="", language="ru", confidence=1.0, duration_ms=1)

    p._stt.transcribe = fake_transcribe  # type: ignore[method-assign]
    p._audio_buffer = [np.zeros(160, dtype=np.float32)]

    await p._process_utterance()

    assert seen_thread, "transcribe was never called"
    assert seen_thread[0] is not threading.main_thread()


def test_stt_beam_size_default_2(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import numpy as np

    from kernel.voice.stt import SpeechToText

    monkeypatch.delenv("KALI_STT_BEAM", raising=False)
    stt = SpeechToText(model_size="base")
    fake_info = MagicMock()
    fake_info.language = "ru"
    fake_info.language_probability = 1.0
    stt._model = MagicMock()
    stt._model.transcribe = MagicMock(return_value=([], fake_info))

    stt.transcribe(np.zeros(160, dtype=np.float32))

    assert stt._model.transcribe.call_args.kwargs["beam_size"] == 2


def test_stt_beam_size_env_override(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import numpy as np

    from kernel.voice.stt import SpeechToText

    monkeypatch.setenv("KALI_STT_BEAM", "5")
    stt = SpeechToText(model_size="base")
    fake_info = MagicMock()
    fake_info.language = "ru"
    fake_info.language_probability = 1.0
    stt._model = MagicMock()
    stt._model.transcribe = MagicMock(return_value=([], fake_info))

    stt.transcribe(np.zeros(160, dtype=np.float32))

    assert stt._model.transcribe.call_args.kwargs["beam_size"] == 5
