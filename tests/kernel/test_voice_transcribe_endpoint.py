"""Default-suite tests for /voice/transcribe.

HTTP-shell behaviour only: validates request schema, auth-free 4xx
mapping, response shape against a mocked SpeechToText. Real STT
integration lives behind the `ml-tests` feature gate.
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from kernel.main import create_app


@pytest.fixture
async def client(monkeypatch):
    app = create_app()

    fake_stt = MagicMock()
    fake_model = MagicMock()
    fake_seg = MagicMock()
    fake_seg.text = "трекер воды"
    fake_info = MagicMock()
    fake_info.language = "ru"
    fake_model.transcribe = MagicMock(return_value=([fake_seg], fake_info))
    fake_stt._model = fake_model
    app.state.stt = fake_stt

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_audio_b64(n_samples: int = 1600) -> str:
    samples = np.zeros(n_samples, dtype="<i2")
    return base64.b64encode(samples.tobytes()).decode("ascii")


async def test_transcribe_returns_text(client):
    r = await client.post(
        "/voice/transcribe",
        json={"audio_b64": _make_audio_b64(), "sample_rate": 16000, "language": "ru"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == "трекер воды"
    assert data["language"] == "ru"
    assert data["duration_ms"] >= 0


async def test_transcribe_rejects_missing_audio(client):
    r = await client.post("/voice/transcribe", json={"sample_rate": 16000})
    assert r.status_code == 400
    assert "audio_b64" in r.json()["error"].lower()


async def test_transcribe_rejects_odd_byte_length(client):
    bad = base64.b64encode(b"\x01\x02\x03").decode("ascii")
    r = await client.post(
        "/voice/transcribe",
        json={"audio_b64": bad, "sample_rate": 16000},
    )
    assert r.status_code == 400
    assert "divisible by 2" in r.json()["error"]


async def test_transcribe_resamples_48khz(client):
    """The endpoint forwards `sample_rate` to the helper; resample is
    transparent. We pass `language="ru"` so the test hits the same
    mocked `_model.transcribe` branch.
    """
    r = await client.post(
        "/voice/transcribe",
        json={"audio_b64": _make_audio_b64(4800), "sample_rate": 48000, "language": "ru"},
    )
    assert r.status_code == 200
