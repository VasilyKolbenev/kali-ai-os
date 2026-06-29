from pathlib import Path

import av
import numpy as np
import pytest

from kernel.reel import generator as gen


class _StubResp:
    text = "Привет! Я chef."
    tool_calls = None
    provider_used = "stub"
    latency_ms = 0


class _Router:
    async def route(self, request):  # noqa: ANN001
        return _StubResp()


@pytest.mark.asyncio
async def test_generate_reel_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        gen, "synthesize_voice_clip",
        lambda text: ((0.1 * np.sin(np.linspace(0, 200, 24000))).astype(np.float32), 24000),
    )
    out = await gen.generate_reel(
        name="chef", description="повар-помощник",
        link="kali://import?n=chef&d=AAAA", router=_Router(), out_dir=tmp_path,
    )
    assert out.exists()
    with av.open(str(out)) as c:
        assert any(s.type == "video" for s in c.streams)
        assert any(s.type == "audio" for s in c.streams)
