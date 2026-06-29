import av
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from tests.e2e._reel_harness import build_app_with_agent


@pytest.mark.core_loop
@pytest.mark.asyncio
async def test_reel_route_returns_mp4(tmp_path, monkeypatch) -> None:
    import kernel.reel.audio as reel_audio
    monkeypatch.setattr(
        reel_audio, "generate_audio",
        lambda text, language=None: ((0.1 * np.sin(np.linspace(0, 200, 24000))).astype(np.float32), 24000),
    )
    app = build_app_with_agent(tmp_path, name="chef", description="повар-помощник")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/skills/chef/reel")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    assert len(r.content) > 0
    out = tmp_path / "got.mp4"
    out.write_bytes(r.content)
    with av.open(str(out)) as ct:
        assert any(s.type == "video" for s in ct.streams)
        assert any(s.type == "audio" for s in ct.streams)


@pytest.mark.core_loop
@pytest.mark.asyncio
async def test_reel_route_honest_fail_unknown_agent(tmp_path) -> None:
    app = build_app_with_agent(tmp_path, name="chef", description="x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/skills/no-such-agent/reel")
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@pytest.mark.core_loop
@pytest.mark.asyncio
async def test_reel_route_falls_back_to_error_when_tts_dies(tmp_path, monkeypatch) -> None:
    import kernel.reel.audio as reel_audio

    def _boom(text, language=None):
        raise RuntimeError("no TTS engine")

    monkeypatch.setattr(reel_audio, "generate_audio", _boom)
    app = build_app_with_agent(tmp_path, name="chef", description="x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/skills/chef/reel")
    assert r.status_code == 200
    assert r.json()["status"] == "error"
