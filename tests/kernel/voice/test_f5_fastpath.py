"""F5 fast-path: cached reference + direct infer_batch_process (no GPU).

api.F5TTS.infer re-reads and re-hashes the 9.6s reference WAV, reseeds RNG and
prints per call — the fast path caches the loaded reference once and calls
infer_batch_process directly with env-tunable NFE/CFG.
"""
from unittest.mock import MagicMock

import numpy as np
import pytest

import kernel.voice.tts_engine_f5 as f5_mod


@pytest.fixture(autouse=True)
def reset_ref_cache():
    f5_mod._ref_cache = None
    yield
    f5_mod._ref_cache = None


@pytest.fixture
def fake_infra(monkeypatch):
    """Mock preprocess/torchaudio/infer_batch_process; count loads, capture kwargs."""
    state: dict = {"loads": 0, "calls": [], "batches": []}

    def fake_preprocess(ref_file, ref_text, show_info=print):
        return "clipped.wav", ref_text + ". "

    fake_torchaudio = MagicMock()

    def fake_load(path):
        state["loads"] += 1
        return np.zeros((1, 24000), dtype=np.float32), 24000

    fake_torchaudio.load = fake_load

    def fake_infer_batch(ref_audio, ref_text, batches, model, vocoder, **kwargs):
        state["calls"].append(kwargs)
        state["batches"].append(list(batches))
        yield np.ones(2400, dtype=np.float32), 24000, None

    monkeypatch.setattr(f5_mod, "_get_f5", lambda: MagicMock(
        ema_model=MagicMock(), vocoder=MagicMock(),
        mel_spec_type="vocos", device="cpu",
    ))
    monkeypatch.setattr(
        "f5_tts.infer.utils_infer.preprocess_ref_audio_text", fake_preprocess
    )
    monkeypatch.setattr("torchaudio.load", fake_load)
    monkeypatch.setattr(
        "f5_tts.infer.utils_infer.infer_batch_process", fake_infer_batch
    )
    return state


def test_reference_loaded_once_across_synths(fake_infra) -> None:
    f5 = f5_mod._get_f5()
    f5_mod._infer_sentence(f5, "Привет, сэр.")
    f5_mod._infer_sentence(f5, "Как дела?")
    assert fake_infra["loads"] == 1


def test_infer_kwargs_from_env(fake_infra, monkeypatch) -> None:
    monkeypatch.setenv("KALI_F5_NFE", "7")
    monkeypatch.setenv("KALI_F5_CFG", "1.5")
    f5 = f5_mod._get_f5()
    f5_mod._infer_sentence(f5, "Привет.")
    kwargs = fake_infra["calls"][0]
    assert kwargs["nfe_step"] == 7
    assert kwargs["cfg_strength"] == 1.5
    assert kwargs["progress"] is None


def test_infer_defaults_without_env(fake_infra, monkeypatch) -> None:
    monkeypatch.delenv("KALI_F5_NFE", raising=False)
    monkeypatch.delenv("KALI_F5_CFG", raising=False)
    f5 = f5_mod._get_f5()
    f5_mod._infer_sentence(f5, "Привет.")
    kwargs = fake_infra["calls"][0]
    # 16 = EPSS-16, quality-gate PASS + ear-verified 2026-07-12 (NFE7 rejected).
    assert kwargs["nfe_step"] == 16
    assert kwargs["cfg_strength"] == 2.0


# ── F5 duration budget (root cause of «не договаривает», 2026-07-15) ────────
#
# F5 generates at most 22 s TOTAL (reference + speech). infer_process guards
# this by computing max_chars from the reference and running chunk_text; the
# fast path bypassed infer_process, so a sentence over the budget was handed to
# the model whole and its tail was silently never synthesized.
#
# chunk_text counts BYTES — Cyrillic is 2 bytes/char, so Russian burns the
# budget twice as fast as Latin: ~287 bytes ≈ 143 characters with our 9.62 s
# reference. That is an ordinary assistant sentence, which is why Vasily heard
# it "often".

#: Real production reference: jarvis_ref_v2.wav — 9.6167 s, 223-byte ref text.
#: Exact duration matters: rounding it to 9.62 shifts the budget by a byte.
REAL_REF_BYTES = 223
REAL_REF_SECONDS = 9.616666666666667
#: What production actually gets: ~287 bytes ≈ 143 Cyrillic characters.
REAL_BUDGET = 287


def test_budget_matches_f5_own_formula() -> None:
    """Our budget must equal what infer_process would have computed."""
    budget = f5_mod._max_chars_for_ref("x" * REAL_REF_BYTES, REAL_REF_SECONDS, 1.0)
    assert budget == int(REAL_REF_BYTES / REAL_REF_SECONDS * (22 - REAL_REF_SECONDS) * 1.0)
    assert budget == REAL_BUDGET


def test_long_russian_sentence_is_split_to_fit_the_budget() -> None:
    """A 207-char Russian sentence exceeds the budget and MUST be split.

    Before the fix this went to F5 as one batch and got cut mid-thought.
    """
    sentence = (
        "Я проверил календарь: завтра у вас три встречи, первая в десять утра с "
        "командой разработки, вторая в час дня с инвесторами, и последняя в шесть "
        "вечера — созвон по поводу запуска продукта на следующей неделе."
    )
    assert len(sentence.encode("utf-8")) > 287, "фикстура должна превышать бюджет"

    batches = f5_mod._chunks_for_budget(sentence, "x" * REAL_REF_BYTES, REAL_REF_SECONDS, 1.0)

    assert len(batches) > 1, "длинное предложение должно резаться, иначе хвост не прозвучит"
    for b in batches:
        assert len(b.encode("utf-8")) <= 287, f"чанк {len(b.encode('utf-8'))} байт > бюджета"
    # ничего не потеряно: все слова исходника присутствуют по порядку
    assert "".join(batches).replace(" ", "") == sentence.replace(" ", "")


def test_short_sentence_stays_single_batch() -> None:
    """Анти-регрессия: короткие фразы не должны дробиться (это стоило бы шва)."""
    batches = f5_mod._chunks_for_budget(
        "Конечно, сэр.", "x" * REAL_REF_BYTES, REAL_REF_SECONDS, 1.0
    )
    assert batches == ["Конечно, сэр."]


def test_infer_sentence_passes_multiple_batches_when_over_budget(
    fake_infra, monkeypatch
) -> None:
    """_infer_sentence must hand F5 the SPLIT batches, not the whole sentence."""
    # Mock ref is 1 s / short text → tiny budget, so even a modest sentence splits.
    monkeypatch.setattr(f5_mod, "_max_chars_for_ref", lambda *_: 40)
    f5 = f5_mod._get_f5()
    long_ru = "Первое предложение про погоду. Второе предложение про задачи на завтра."
    f5_mod._infer_sentence(f5, long_ru)
    batches = fake_infra["batches"][0]
    assert len(batches) > 1, f"ожидались чанки, пришло одним куском: {batches}"


def test_generate_audio_synthesizes_per_chunk(fake_infra, monkeypatch) -> None:
    monkeypatch.setattr(f5_mod, "_fix_text", lambda t: t)
    # Two ~90-char sentences: 180 > 150 merge cap → two separate infer calls.
    s1 = "Первое очень длинное предложение " + "о погоде и планах " * 3 + "готово."
    s2 = "Второе очень длинное предложение " + "про задачи и дела " * 3 + "тоже."
    audio, sr = f5_mod.generate_audio(f"{s1} {s2}")
    assert sr == 24000
    assert len(fake_infra["calls"]) == 2
    assert len(audio) == 4800  # two 2400-sample chunks concatenated


def test_split_sentences_merges_to_150_not_300() -> None:
    s60 = "а" * 58 + ". "
    text = (s60 * 3).strip()
    chunks = f5_mod._split_sentences(text)
    assert len(chunks) == 2  # 120 < 150 merges, +60 overflows
