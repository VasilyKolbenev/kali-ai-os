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


async def test_memory_context_prefetched_concurrently_with_stt() -> None:
    """Memory-context fetch overlaps STT instead of running after it —
    proven by wall-clock: 100ms STT + 80ms fetch must finish well under 180ms."""
    import time as _time
    from unittest.mock import AsyncMock, MagicMock

    import numpy as np

    p = _mk()

    def slow_transcribe(audio):
        _time.sleep(0.10)
        from kernel.voice.stt import STTResult
        return STTResult(text="привет", language="ru", confidence=1.0, duration_ms=100)

    async def slow_context() -> str:
        import asyncio
        await asyncio.sleep(0.08)
        return "<UserFacts>\n- Имя: «Вася»\n</UserFacts>\n"

    app_state = MagicMock()
    app_state.long_term_memory.get_user_context_string = slow_context
    app_state.long_term_memory.maybe_extract_and_save_facts = AsyncMock()
    app_state.builder_flow = None
    p._app_state = app_state
    p._stt.transcribe = slow_transcribe  # type: ignore[method-assign]
    p._audio_buffer = [np.zeros(160, dtype=np.float32)]

    captured: dict = {}

    async def fake_route(request):
        captured["system_prompt"] = request.system_prompt
        from kernel.llm_router import LLMResponse
        return LLMResponse(text="", tool_calls=None, provider_used="test", latency_ms=1)

    p._llm.route = fake_route  # type: ignore[method-assign]
    p._llm.route_streaming = None  # not yet ported; route() path in use

    t0 = _time.perf_counter()
    await p._process_utterance()
    elapsed = _time.perf_counter() - t0

    assert elapsed < 0.17, f"prefetch not concurrent: {elapsed:.3f}s (sequential would be ≥0.18)"
    assert captured["system_prompt"] and "Вася" in captured["system_prompt"]


async def test_prefetch_task_cancelled_on_empty_stt() -> None:
    """Early return on empty STT must not leave an orphan context task."""
    import asyncio
    from unittest.mock import MagicMock

    import numpy as np

    p = _mk()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hanging_context() -> str:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return ""

    app_state = MagicMock()
    app_state.long_term_memory.get_user_context_string = hanging_context
    p._app_state = app_state

    def empty_transcribe(audio):
        from kernel.voice.stt import STTResult
        return STTResult(text="", language=None, confidence=0.0, duration_ms=0)

    p._stt.transcribe = empty_transcribe  # type: ignore[method-assign]
    p._audio_buffer = [np.zeros(160, dtype=np.float32)]

    await p._process_utterance()
    await asyncio.sleep(0)  # let cancellation propagate

    assert started.is_set()
    assert cancelled.is_set(), "context prefetch task leaked after empty STT"


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
