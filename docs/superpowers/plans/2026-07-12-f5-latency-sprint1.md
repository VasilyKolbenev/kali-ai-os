# Voice-latency Sprint 1 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Session gotcha (2026-07):** предпочтительно инлайн-исполнение + eager per-task коммиты; фоновые субагенты ненадёжны.

**Goal:** Perceived TTFA (конец речи → первый звук, desktop, прогретый) с ~8–15 с до ≤3 с (stretch ≤2 с) без потери RU-качества F5.

**Architecture:** Три слоя: (A) квалити-гейт + честный замер как ворота; (B) хирургия десктопного пайплайна (silence 900, STT в поток+beam 2, prefetch memory-контекста, порт LLM-стриминга из remote); (C) F5 fast-path (кэш референса через прямой `infer_batch_process`, NFE/CFG через env, первый-клауза-чанк за флагом); (D) EPSS-эксперимент через гейт. Всё откатываемо env-переменными.

**Tech Stack:** Python 3.12 / pytest (asyncio_mode=auto) / f5-tts 1.1.17 (EPSS встроен: `cfm.sample(use_epss=True)` дефолт; `get_epss_timesteps` имеет `7:[0,2,4,6,8,16,24,32]`) / faster-whisper (CER-судья).

**Spec:** `docs/superpowers/specs/2026-07-12-f5-latency-sprint1.md` · **Grounding:** `2026-07-12-f5-latency-grounding.md`

**Коррекции аудита (проверено чтением кода):**
- `maybe_extract_and_save_facts` УЖЕ fire-and-forget (`long_term_memory.py:85` create_task) — пункт «экстракция блокирует TTS» = false positive, задача исключена.
- EPSS не требует кастомного сэмплера: `nfe_step=7` автоматически активирует расписание EPSS-7 (`f5_tts/model/utils.py:205-218`, `cfm.py:211`).
- `api.F5TTS.infer` на каждый вызов: md5-хэш файла + `torchaudio.load` + `seed_everything(random)` + print'ы (`api.py:117-122`, `utils_infer.py:296-307,401`). `infer_batch_process` принимает готовый `(audio, sr)` и `progress=None` (`utils_infer.py:433-452,522-528`) → точка кэша.
- Апгрейд f5-tts (1.1.19 vocos-кэш) — НЕ в критическом пути (мы обходим `infer_process`); отдельный опциональный эксперимент после спринта.

**Documented spec deviations (сознательные):**
- **UTMOS выпадает из гейта v1** (тяжёлая модельная зависимость): инвариант качества = ΔCER + ECAPA-SIM + обязательное ухо Vasily (слепые пары при WARN). UTMOS — кандидат на v2 гейта.
- **Первый-клауза-чанк без DSP cross-fade в v1:** чанки играются встык; спека предлагала fade 0.15с. Механизм контроля — ушной гейт (решение Vasily 2026-07-12: «да, если шов не режет ухо»); слышен шов → добавляем fade в консьюмере или выключаем флаг.

**Гейты после каждого chunk:** `.venv\Scripts\python.exe -m pytest tests/kernel -q` (известные env-DNS исключения) и `-m core_loop` перед пушем. UI/mobile/Rust не трогаем.

---

## Chunk A: Квалити-гейт + честный замер

### Task 1: `scripts/tts_quality_gate.py` + замороженный RU-сет

**Files:**
- Create: `scripts/tts_quality_gate.py`
- Create: `tests/fixtures/tts_gate_phrases.txt` (25 фраз)
- Test: `tests/kernel/voice/test_quality_gate.py` (create; каталог tests/kernel/voice/ уже есть — проверить, иначе создать с `__init__.py` по соседству)

Сет фраз (числа/имена/вопросы/«сэр»/длинные) — 25 строк, например: «Доброе утро, сэр. Сегодня двенадцатое июля.», «Напомнить Василисе про встречу в три тридцать?», «Температура за окном минус восемь градусов.», «Готово, сэр. Я создал три новых агента.» … **Минимум 3 фразы длиннее 160 символов** (контроль обхода chunk_text-батчинга при прямом infer_batch_process — см. Task 8). Полный сет пишется при имплементации, фиксируется в файле и НЕ меняется между экспериментами.

- [ ] **Step 1: Write failing tests** — чистые юнит-тесты логики гейта (без GPU):

```python
"""Quality-gate scoring logic (no GPU, no models — pure functions)."""
from scripts.tts_quality_gate import GateThresholds, Verdict, score_experiment


def test_pass_when_all_deltas_within_thresholds() -> None:
    v = score_experiment(
        baseline={"cer": 0.05, "sim": 0.80},
        candidate={"cer": 0.052, "sim": 0.79},
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.PASS


def test_fail_on_cer_regression() -> None:
    v = score_experiment(
        baseline={"cer": 0.05, "sim": 0.80},
        candidate={"cer": 0.061, "sim": 0.80},  # +1.1 п.п. > 0.5
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.FAIL
    assert "cer" in v.reasons[0].lower()


def test_warn_zone_requests_blind_ab() -> None:
    v = score_experiment(
        baseline={"cer": 0.05, "sim": 0.80},
        candidate={"cer": 0.054, "sim": 0.785},  # sim −0.015: в warn-зоне ≤0.02
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.WARN


def test_sim_none_degrades_to_warn_not_crash() -> None:
    # ECAPA (speechbrain) может быть не установлен — гейт честно WARN, не падает.
    v = score_experiment(
        baseline={"cer": 0.05, "sim": None},
        candidate={"cer": 0.05, "sim": None},
        thresholds=GateThresholds(),
    )
    assert v.verdict == Verdict.WARN
```

- [ ] **Step 2: Run — verify FAIL** (`.venv\Scripts\python.exe -m pytest tests/kernel/voice/test_quality_gate.py -q` → ImportError)
- [ ] **Step 3: Implement `scripts/tts_quality_gate.py`:**
  - `GateThresholds` dataclass: `max_cer_delta=0.005` (+0.5 п.п.), `max_sim_drop=0.02`, warn-зона = попадание в порог ближе 50%: cer_delta > 0.0025 или sim_drop > 0.01 → WARN.
  - `Verdict` enum PASS/WARN/FAIL; `score_experiment(baseline, candidate, thresholds) -> GateResult(verdict, reasons)`; `sim=None` (нет ECAPA) → минимум WARN c reason «SIM skipped».
  - Runner-часть (под `if __name__ == "__main__"`): `--config nfe=7` style kv-переопределения env → для каждой фразы из `tests/fixtures/tts_gate_phrases.txt` синтез через `kernel.voice.tts_router.generate_audio` (env применён) → WAV в `artifacts/tts_gate/<run-name>/` → CER: транскрибировать существующим faster-whisper (паттерн `scripts/measure_voice_latency.py`, модель «small», сравнение с нормализованным текстом фразы, `jiwer` НЕ добавлять — простая левенштейн-реализация в скрипте) → SIM: `try: from speechbrain.inference import EncoderClassifier` (ECAPA voxceleb) cosine к `models/jarvis_ref_v2.wav`, `except ImportError → sim=None` (честный лог). Результат `run.json` + сравнение с `artifacts/tts_gate/<baseline>/run.json` (флаг `--baseline`, дефолт `baseline`) → таблица PASS/WARN/FAIL.
  - Логирование через `logging`, type hints, docstrings (Google style).
- [ ] **Step 4: Run — verify PASS**
- [ ] **Step 5: Commit** `git add scripts/tts_quality_gate.py tests/fixtures/tts_gate_phrases.txt tests/kernel/voice/test_quality_gate.py && git commit -m "feat(voice): TTS quality gate — frozen RU set, CER+SIM scoring, PASS/WARN/FAIL"`

### Task 2: Обновить `scripts/measure_voice_latency.py`

**Files:**
- Modify: `scripts/measure_voice_latency.py`
- Test: smoke-запуск (GPU-скрипт, юнитов нет)

- [ ] **Step 1:** Переписать TTS-часть: `load_models` → **warmup-синтез (discard, отдельной строкой в отчёте)** → замер 3×short(«Да, сэр.»)/3×med/2×long прогретых, медианы + RTF; silence-константу в сводке читать из `KALI_SILENCE_MS` (дефолт как в pipeline), НЕ хардкод 700; STT-модель из `config/kali.yaml` voice.stt_model (сейчас скрипт хардкодит "base"); STT-стадию обернуть в `faulthandler.dump_traceback_later(120)`-таймаут-заметку (залипание 2026-07-12 — известный риск) и сделать пропускаемой флагом `--skip-stt`; сводка «TTFA now» = silence + STT + LLM + TTS_first(short warm).
- [ ] **Step 2: Smoke:** `.venv\Scripts\python.exe scripts\measure_voice_latency.py --skip-stt` (фоново, GPU) → печатает warm-медианы. Expected: short warm ≈ 3.5с (сойдётся с ручным замером 2026-07-12).
- [ ] **Step 3: Commit** `git add scripts/measure_voice_latency.py && git commit -m "fix(voice): honest P0 latency measure — warmup, warm medians, real constants"`

### Task 3: Baseline-прогон гейта (RTX)

- [ ] **Step 1:** `.venv\Scripts\python.exe scripts\tts_quality_gate.py --run-name baseline` (текущий конфиг NFE=32) → `artifacts/tts_gate/baseline/run.json` + WAVы.
- [ ] **Step 2:** Приложить сводку baseline в `docs/superpowers/specs/2026-07-12-f5-latency-sprint1.md` (секция «Baseline», appended). `artifacts/` в .gitignore — проверить; коммитить только run.json baseline (маленький) в `docs/superpowers/data/2026-07-12-tts-baseline.json`.
- [ ] **Step 3: Commit** докой.

## Chunk B: Хирургия пайплайна (`kernel/voice/pipeline.py`)

### Task 4: KALI_SILENCE_MS 2500 → 900

**Files:**
- Modify: `kernel/voice/pipeline.py:132-138`
- Test: `tests/kernel/voice/test_pipeline_latency.py` (create)

- [ ] **Step 1: Failing test:**

```python
"""Latency-surgery invariants of the desktop voice pipeline."""
import os
from unittest.mock import MagicMock, patch

from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import VoicePipeline


def _mk(monkeypatch=None) -> VoicePipeline:
    from kernel.event_bus import EventBus
    return VoicePipeline(EventBus(), VoiceConfig(), LLMConfig(), tools=[])


def test_default_silence_window_is_900ms(monkeypatch) -> None:
    monkeypatch.delenv("KALI_SILENCE_MS", raising=False)
    p = _mk()
    assert p._max_silence_chunks == 900 // 32  # 28 chunks


def test_silence_window_env_override(monkeypatch) -> None:
    monkeypatch.setenv("KALI_SILENCE_MS", "2500")
    p = _mk()
    assert p._max_silence_chunks == 2500 // 32
```

(Проверить конструктор VoicePipeline: если EventBus/VoiceConfig требуют иные аргументы — подстроить `_mk` по факту; см. существующие тесты `tests/kernel/voice/` за паттерном инстанцирования.)
- [ ] **Step 2: verify FAIL** (28 != 78)
- [ ] **Step 3:** В `pipeline.py:137` дефолт `"2500"` → `"900"`; комментарий: «900 мс — Rust-путь живёт с 960 (config.rs); откат: KALI_SILENCE_MS=2500 если вернутся обрывы "на подумать" (2026-06: причина прежнего повышения)».
- [ ] **Step 4: verify PASS** + весь `tests/kernel/voice -q`
- [ ] **Step 5: Commit** `feat(voice): default end-of-speech silence 2500→900ms (env-revertible)`

### Task 5: STT в to_thread + beam_size 2

**Files:**
- Modify: `kernel/voice/pipeline.py:328` · `kernel/voice/stt.py` (beam-параметр)
- Test: `tests/kernel/voice/test_pipeline_latency.py` (append), `tests/kernel/voice/test_stt*.py` (найти существующий, append)

- [ ] **Step 1: Failing tests:** (а) `transcribe` вызывается через `asyncio.to_thread` — мок `self._stt.transcribe` sync-функцией со сном 50мс + конкурентная задача-канарейка успевает выполниться (event loop не заблокирован); (б) `SpeechToText` принимает `beam_size` (env `KALI_STT_BEAM`, дефолт 2) и передаёт в `_model.transcribe` (мок-модель, паттерн `test_voice_transcribe_endpoint.py`).
- [ ] **Step 2: verify FAIL**
- [ ] **Step 3:** `pipeline.py:328`: `stt_result = await asyncio.to_thread(self._stt.transcribe, audio)` (паттерн `remote_pipeline.py:139`). `stt.py`: `beam_size=int(os.environ.get("KALI_STT_BEAM", "2"))` в вызове `_model.transcribe` (найти текущее `beam_size=5`; сохранить остальные kwargs).
- [ ] **Step 4: verify PASS**; ПРИМЕЧАНИЕ: WER-эффект beam 5→2 на RU проверяется гейтом Task 10 (CER-судья сам на beam из env → для судейства фиксировать `KALI_STT_BEAM=5` внутри gate-скрипта, чтобы судья не деградировал вместе с кандидатом!).
- [ ] **Step 5: Commit** `feat(voice): STT off the event loop + beam_size env (default 2)`

### Task 6: Prefetch memory-контекста параллельно STT

**Files:**
- Modify: `kernel/voice/pipeline.py:319-335` (`_process_utterance`) + `:431-444` (`_handle_transcription`)
- Test: append `test_pipeline_latency.py`

- [ ] **Step 1: Failing test:** мок `lt_memory.get_user_context_string` (async, 50мс сон, счётчик) + мок STT (100мс) → в `_process_utterance` оба стартуют конкурентно: суммарное время < 140мс (не 150+), контекст передан в `_handle_transcription` (LLMRequest.system_prompt содержит факт-строку — мок LLM ловит request).
- [ ] **Step 2: verify FAIL**
- [ ] **Step 3:** В `_process_utterance`: `ctx_task = asyncio.create_task(self._fetch_memory_context())` ДО `to_thread(stt)`; после STT `facts_context = await ctx_task`; передать в `_handle_transcription(stt_result, facts_context)`. Вынести текущий try/except-блок (:437-441) в `_fetch_memory_context() -> str`.
  - **Сигнатура с дефолтом:** `_handle_transcription(self, stt_result, facts_context: str | None = None)`; `None` → вызвать `_fetch_memory_context()` внутри (fallback) — существующие 7 call-sites в тестах (`tests/kernel/test_pipeline.py:88`, `test_pipeline_builder_integration.py` ×5, `tests/test_voice_tool_dispatch.py:166`) остаются валидными без правок.
  - **Empty-STT ветка** (`_process_utterance:329-332` ранний return): `ctx_task.cancel()` перед return (не оставлять orphan-task).
- [ ] **Step 4: verify PASS** + весь voice-suite
- [ ] **Step 5: Commit** `feat(voice): prefetch memory context concurrently with STT`

### Task 7: Порт LLM-стриминга в local-пайплайн (главная задача chunk B)

**Files:**
- Modify: `kernel/voice/pipeline.py` (`_handle_transcription` ветка 4 + `_play_tts_with_guard`)
- Test: `tests/kernel/voice/test_pipeline_streaming.py` (create)

Дизайн (зеркало `remote_pipeline.py:195-206`, адаптированное под локальный playback-guard): не ждать полного `route()`. Новый метод `_speak_streaming_response(request) -> LLMResponse`:

```python
    async def _speak_streaming_response(self, request: LLMRequest) -> LLMResponse:
        """Stream the LLM reply into sentence-level TTS playback (P1 port of
        remote_pipeline): sentence 1 plays while the LLM still generates the
        rest. Returns the full response for context/tool handling. Tool-call
        turns produce an empty stream (recovered non-streamed by the router) —
        their result is spoken by the caller via _play_tts_with_guard.
        """
        from kernel.voice.sentence_buffer import SentenceBuffer

        was_recording = self._recorder.is_recording
        await self._set_state(PipelineState.SPEAKING)
        if was_recording:
            await self._recorder.stop()
        queue: asyncio.Queue[tuple[np.ndarray, int] | None] = asyncio.Queue()
        spoke_any = False

        async def synth(sentence: str) -> None:
            # TTS failure must NEVER propagate: it would skip the caller's
            # IDLE transition and deafen the pipeline until restart (parity
            # with generate_task in _play_tts_with_guard).
            nonlocal spoke_any
            try:
                async for audio, sr in tts_router.generate_audio_stream(sentence):
                    if len(audio) > 0:
                        spoke_any = True
                        await queue.put((audio, sr))
            except Exception:
                logger.exception("Streaming TTS failed on %r", sentence[:40])

        async def consumer() -> None:
            while True:
                item = await queue.get()
                if item is None:
                    return
                audio, sr = item
                await asyncio.to_thread(_play_audio, audio, sr)

        consumer_task = asyncio.create_task(consumer())
        sb = sentence_buffer_from_env()
        try:
            async def on_delta(delta: str) -> None:
                for sentence in sb.feed(delta):
                    await synth(sentence)

            response = await self._llm.route_streaming(request, on_delta)
            tail = sb.flush()
            if tail and not response.tool_calls:
                await synth(tail)
        finally:
            await queue.put(None)
            await consumer_task
            if spoke_any:
                # anti-echo drain only if speakers actually said something —
                # a silent tool-call turn shouldn't pay 0.5s for nothing.
                await asyncio.sleep(0.5)
            if was_recording:
                await self._recorder.start()
            self._wake_word.reset()
            self._vad.reset()
            self._audio_buffer.clear()
            self._silence_count = 0
            self._speech_active = False
        return response
```

Обязательные детали интеграции:
- **Импорт:** `from kernel.llm_router import LLMRequest, LLMResponse, LLMRouter` (сейчас `LLMResponse` НЕ импортирован в pipeline.py — аннотация выбросит NameError при определении класса).
- **IDLE остаётся у вызывающего:** `_speak_streaming_response` сам НЕ ставит IDLE; существующий `await self._set_state(PipelineState.IDLE)` в конце `_handle_transcription` (:500) — load-bearing, не удалять.
- `sentence_buffer_from_env()` — фабрика из Task 9; до Task 9 использовать `SentenceBuffer()` напрямую и переключить в Task 9.

В `_handle_transcription` ветка 4: `response = await self._speak_streaming_response(request)` вместо `route()`; после tool-dispatch: если `response.tool_calls` и есть `final_text` — озвучить его существующим `_play_tts_with_guard(final_text)`; если стрим уже проговорил текст (`not response.tool_calls`) — НЕ вызывать `_play_tts_with_guard` повторно (убрать безусловный `if final_text: await self._play_tts_with_guard(final_text)` для этой ветки). Событие `agent.response` публикуется как раньше (после стрима — текст уже полный).

**Совместимость существующих тестов:** `tests/kernel/test_pipeline.py::test_transcription_emits_event` мокает только `_llm.route` и полагается на проглатывание TTS-ошибок — после порта он пойдёт через `route_streaming`-фолбэк (нестримовый провайдер эмитит полный текст одной дельтой) и synth-обёртку с try/except; прогнать и при падении обновить мок на `route_streaming` (сохранив смысл теста).

ВНИМАНИЕ РЕВЬЮЕРУ: `synth()` внутри `on_delta` — синтез ПОСЛЕДОВАТЕЛЕН с приёмом дельт (await внутри колбэка тормозит чтение стрима). Это сознательно (как в remote: `_on_delta` тоже await'ит `_emit_tts_for`): синтез предложения N перекрывается ПЛЕЙБЕКОМ N−1 через очередь; параллелить синтез с приёмом дельт — усложнение без выигрыша (F5 на 8GB всё равно однопоточен по GPU).

- [ ] **Step 1: Failing tests** (мок `tts_router.generate_audio_stream` — быстрые фейк-аудио; мок `route_streaming` — дельты с паузами; мок `_play_audio` — счётчик с задержкой):
  1. первый аудио-чанк уходит в playback ДО завершения route_streaming (стрим ещё держится на Event — а `_play_audio`-мок уже вызван);
  2. tool_call-ход (route_streaming возвращает tool_calls, пустой стрим) → стрим-путь молчит, `final_text` уходит через `_play_tts_with_guard` ровно один раз;
  3. рекордер: stop до первого чанка, start после; wake/vad reset вызваны (моки);
  4. обычный ход НЕ вызывает `_play_tts_with_guard` (нет двойного проговаривания).
- [ ] **Step 2: verify FAIL**
- [ ] **Step 3: Implement** (код выше + правка ветки 4)
- [ ] **Step 4: verify PASS** + весь `tests/kernel -q`
- [ ] **Step 5: Commit** `feat(voice): stream LLM→sentence-TTS in the desktop pipeline (P1 port)`

## Chunk C: F5 fast-path (`kernel/voice/tts_engine_f5.py`)

### Task 8: Кэш референса + прямой infer_batch_process + env-параметры

**Files:**
- Modify: `kernel/voice/tts_engine_f5.py:88-96,225-298`
- Test: `tests/kernel/voice/test_f5_fastpath.py` (create)

Дизайн: модульный `_RefCache` (preprocess+load один раз) + `_infer_sentence(f5, sentence) -> np.ndarray`, используемый и `generate_audio`, и `generate_audio_stream`:

```python
def _nfe() -> int:
    """Read per call so tests can monkeypatch env without module reload.
    7 активирует встроенный EPSS-7 (f5_tts/model/utils.py:205)."""
    return int(os.environ.get("KALI_F5_NFE", "32"))


def _cfg() -> float:
    return float(os.environ.get("KALI_F5_CFG", "2.0"))


_ref_cache: tuple[Any, int, str] | None = None  # (audio_tensor, sr, ref_text)

def _get_ref() -> tuple[Any, int, str]:
    """Preprocess + load the reference ONCE (api.infer re-reads and re-hashes
    the 9.6s WAV from disk on EVERY call — measured ~hundreds of ms)."""
    global _ref_cache
    if _ref_cache is None:
        import torchaudio
        from f5_tts.infer.utils_infer import preprocess_ref_audio_text
        ref_file, ref_text = preprocess_ref_audio_text(
            str(REFERENCE_AUDIO), _get_processed_reference_text(),
            show_info=lambda *_: None,
        )
        audio, sr = torchaudio.load(ref_file)
        _ref_cache = (audio, sr, ref_text)
    return _ref_cache

def _infer_sentence(f5: Any, sentence: str) -> np.ndarray:
    """One sentence through cached-ref infer_batch_process (no disk I/O,
    no seed_everything, no tqdm/print — the api.infer per-call overhead)."""
    from f5_tts.infer.utils_infer import infer_batch_process
    audio, sr, ref_text = _get_ref()
    wav, out_sr, _spec = next(infer_batch_process(
        (audio, sr), ref_text, [sentence], f5.ema_model, f5.vocoder,
        mel_spec_type=f5.mel_spec_type, progress=None,
        nfe_step=_nfe(), cfg_strength=_cfg(),
        sway_sampling_coef=-1, speed=SPEED, device=f5.device,
    ))
    return np.asarray(wav, dtype=np.float32)
```

**Обязательно вместе с обходом `infer_process`:** его `chunk_text`-батчинг (utils_infer.py:400-403) резал gen_text до ~160–170 RU-символов под наш 9.6с-референс, а наш `_split_sentences` мержит до **300** — без правки длинные мержи пойдут в `sample()` одним куском с непроверенной длительностью (реальное отличие поведения, не только оверхед). → В `_split_sentences` (tts_engine_f5.py:214) порог 300 → **150**. Гейт-сет Task 1 обязан содержать 3+ длинные фразы (>160 симв.), чтобы это изменение было под контролем качества.

`generate_audio` / `generate_audio_stream`: заменить `f5.infer(...)`-вызовы на `_infer_sentence` (stream — через `asyncio.to_thread(_infer_sentence, f5, sentence)`); нормализация peak 0.7 остаётся у вызывающих как сейчас. `REMOVE_SILENCE` использовался только через api.infer (False) — дропается без изменения поведения. Env-параметры читать на импорте модуля (как сейчас константы), для тестов — `importlib.reload` или чтение в функции: **читать в функции** (`_nfe()`, `_cfg()`) чтобы monkeypatch.setenv работал без reload.

- [ ] **Step 1: Failing tests** (все — с моками `preprocess_ref_audio_text`/`torchaudio.load`/`infer_batch_process`, БЕЗ GPU):
  1. два вызова `_infer_sentence` → `torchaudio.load` вызван один раз (кэш);
  2. `infer_batch_process` получил `progress=None`, `nfe_step` из `KALI_F5_NFE` (monkeypatch env → 7), `cfg_strength` из `KALI_F5_CFG`;
  3. дефолты без env: nfe 32, cfg 2.0;
  4. `generate_audio` на 2-предложенном тексте вызывает `_infer_sentence` дважды и конкатенирует;
  5. `_split_sentences` мержит до 150 симв. (не 300): текст из трёх 60-символьных предложений → 2 чанка.
- [ ] **Step 2: verify FAIL** → **Step 3: Implement** → **Step 4: verify PASS** (+ voice-suite)
- [ ] **Step 5: GPU-подтверждение:** `measure --skip-stt`: short warm ДОЛЖЕН упасть заметно ниже 3.5с (кэш+no-print). Числа в отчёт.
- [ ] **Step 6: Commit** `feat(voice): F5 fast-path — cached reference, direct infer_batch_process, NFE/CFG via env`

### Task 9: Первый-клауза-чанк за флагом

**Files:**
- Modify: `kernel/voice/sentence_buffer.py`
- Test: `tests/kernel/test_sentence_buffer.py` (СУЩЕСТВУЕТ по этому пути — append, НЕ создавать дубликат в voice/)

- [ ] **Step 1: Failing tests:** `SentenceBuffer(first_clause=True)`: (а) фид «Конечно, сэр. Сейчас всё проверю.» по кускам → первым эмитится «Конечно,» (клауза ≥8 симв. на границе `[,;:—]` + пробел) не дожидаясь точки; (б) короче 8 симв. до запятой — не эмитится (ждёт полного предложения); (в) **клауза-эмит НЕ расходует first-sentence fast-path:** после «Конечно,» остаток «сэр. …» при закрытии эмитится немедленно (порог 1, не min_chars=40) — т.е. `_first_emitted` выставляется только полным предложением; (г) `first_clause=False` (дефолт) — поведение байт-в-байт прежнее (существующие 20 тестов зелёные без правок); (д) фабрика `sentence_buffer_from_env()` читает `KALI_TTS_FIRST_CLAUSE=1`.
- [ ] **Step 2: verify FAIL** → **Step 3:** доп. regex `_CLAUSE_BOUNDARY = re.compile(r"[,;:—]\s")` + отдельный флаг `_clause_emitted` (не трогающий `_first_emitted`): в `feed()`, пока `not self._first_emitted and not self._clause_emitted` и в `self._buf` есть клауза-граница c length≥8 — эмитить клаузу немедленно, `_clause_emitted=True`. `flush()` сбрасывает оба. Фабрика `sentence_buffer_from_env()`; использовать её в `pipeline._speak_streaming_response` и `tts_router.generate_audio_by_sentence`.
- [ ] **Step 4: verify PASS** → **Step 5: Commit** `feat(voice): first-clause TTS chunk behind KALI_TTS_FIRST_CLAUSE`

## Chunk D: EPSS-эксперимент + отчёт

### Task 10: Гейт-прогоны fast-path/NFE (RTX, runner)

- [ ] **Step 0 (изоляция переменных):** после Task 8 прогнать `--run-name nfe32-fastpath` (env-дефолты) и сравнить с baseline (Task 3, старый api.infer-путь): baseline и кандидаты иначе отличались бы сразу ДВУМЯ переменными (fast-path: нет per-call seed_everything/чанкинга + порог 150) — PASS здесь обязателен до NFE-экспериментов.
- [ ] **Step 1:** `tts_quality_gate.py --run-name nfe7 --env KALI_F5_NFE=7`, `--run-name nfe16 --env KALI_F5_NFE=16` (фоново, последовательно — GPU один).
- [ ] **Step 2:** Таблица nfe32-fastpath vs nfe16 vs nfe7: CER/SIM/verdict + synth-медианы. PASS → кандидат = nfe7; WARN → слепой A/B для Vasily (пары WAV из artifacts); FAIL nfe7 → кандидат nfe16.
- [ ] **Step 3:** **ПАУЗА: ухо Vasily** — прослушать 3–5 пар baseline-vs-кандидат (обязательный шаг, объективные метрики недооценивают тембр). Только после его «голос тот же» → Step 4.
- [ ] **Step 4:** Флип дефолта `KALI_F5_NFE` в коде на выбранное значение + тест-обновление + commit `feat(voice): default NFE → <N> (EPSS, quality-gate passed + ear-verified)`.

### Task 11: Финальный замер + отчёт + пуш

- [ ] **Step 1:** Полный `measure_voice_latency.py` (со всеми стадиями) → сравнение с baseline: TTFA-оценка ≤3с?
- [ ] **Step 2:** Дописать «Results»-секцию в спеку (baseline/after, все env-флаги и дефолты). Данные-json в `docs/superpowers/data/`.
- [ ] **Step 3:** Гейты: `pytest tests/kernel -q` + `-m core_loop`. Всё зелёное → `git push origin main`.
- [ ] **Step 4:** Обновить memory (`project`-запись спринта; latency-цифры до/после) + предложить Vasily живой голосовой тест (секундомер + ухо) — финальная верификация DoD.

## Вне плана (записано, не делать в спринте)
Апгрейд f5-tts ≥1.1.19 (эксперимент после; мы обошли infer_process) · cfg_strength=0 (отдельный ушной эксперимент) · torch.compile (замер по желанию) · Anthropic-стриминг (прод = openai) · Rust Gate A · дистилляция (фаза 2).
