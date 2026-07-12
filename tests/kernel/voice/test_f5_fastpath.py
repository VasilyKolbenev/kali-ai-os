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
    state = {"loads": 0, "calls": []}

    def fake_preprocess(ref_file, ref_text, show_info=print):
        return "clipped.wav", ref_text + ". "

    fake_torchaudio = MagicMock()

    def fake_load(path):
        state["loads"] += 1
        return np.zeros((1, 24000), dtype=np.float32), 24000

    fake_torchaudio.load = fake_load

    def fake_infer_batch(ref_audio, ref_text, batches, model, vocoder, **kwargs):
        state["calls"].append(kwargs)
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
    assert kwargs["nfe_step"] == 32
    assert kwargs["cfg_strength"] == 2.0


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
