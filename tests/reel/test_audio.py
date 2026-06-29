import numpy as np

from kernel.reel import audio as reel_audio


def test_synthesize_normalizes_to_float32_mono(monkeypatch) -> None:
    # Provider returns stereo int16 — must come back float32 mono.
    fake = (np.zeros((100, 2), dtype=np.int16), 24000)
    monkeypatch.setattr(reel_audio, "generate_audio", lambda text, language=None: fake)
    clip, sr = reel_audio.synthesize_voice_clip("привет")
    assert clip.dtype == np.float32
    assert clip.ndim == 1
    assert sr == 24000


def test_synthesize_passes_mono_through(monkeypatch) -> None:
    fake = (np.ones(50, dtype=np.float32), 22050)
    monkeypatch.setattr(reel_audio, "generate_audio", lambda text, language=None: fake)
    clip, sr = reel_audio.synthesize_voice_clip("привет")
    assert clip.shape == (50,)
    assert sr == 22050
