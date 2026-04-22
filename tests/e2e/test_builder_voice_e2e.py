"""End-to-end builder: simulated STT input → deployed skill, wall-clock <60s."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


class _MockIntent:
    def __init__(self, type_: str = "skill", template: str = "reminder") -> None:
        self.type = type_
        self.template = template
        self.confidence = 0.9
        self.reason = "mocked"


@pytest.mark.asyncio
async def test_builder_e2e_water_reminder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate: voice → "напомни пить воду" → answers → deploy → skill on disk, <60s."""
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: _MockIntent(),
    )

    from kernel.builder.flow import BuilderFlow
    from kernel.builder.session_store import SessionStore
    from kernel.main import create_app

    app = create_app()
    agents_dir = tmp_path / "agents"
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    app.state.builder_flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=agents_dir,
        skill_executor=executor,
    )

    start_time = time.monotonic()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/builder/start",
            json={"request": "напомни пить воду каждые 2 часа"},
        )
        assert r.status_code == 200
        sid = r.json()["session_id"]
        total = r.json()["total_steps"]

        answers = ["каждые 2 часа", "с 9 утра до 10 вечера", "голосом"]
        for i in range(total):
            answer = answers[i] if i < len(answers) else "default"
            r = await c.post(
                "/builder/answer",
                json={"session_id": sid, "answer": answer},
            )
            assert r.status_code == 200

        r = await c.post("/builder/deploy", json={"session_id": sid})
        assert r.status_code == 200
        assert r.json()["status"] == "deployed"

    elapsed = time.monotonic() - start_time
    assert elapsed < 60.0, f"Flow took {elapsed:.1f}s — exceeds 60s budget"

    # Verify skill files written
    skill_dirs = list(agents_dir.iterdir())
    assert len(skill_dirs) == 1
    assert (skill_dirs[0] / "manifest.yaml").exists()
    assert (skill_dirs[0] / "skill.yaml").exists()
