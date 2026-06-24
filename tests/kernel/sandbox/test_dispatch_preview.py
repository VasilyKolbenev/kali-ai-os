"""The sandbox dispatch enriches its audit record with a plain-language preview."""

from typing import Any

from kernel.sandbox.backend import DispatchRequest, InProcessSandbox


class _FakeRuntime:
    """Minimal agent_runtime stub: records the call and returns a result."""

    async def dispatch(self, name: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


async def test_dispatch_audit_record_carries_preview() -> None:
    captured: list[dict[str, Any]] = []
    sandbox = InProcessSandbox(agent_runtime=_FakeRuntime(), audit_sink=captured.append)

    await sandbox.dispatch(
        DispatchRequest(agent_name="email", action="send_email", args={"to": "a@b.com"})
    )

    assert len(captured) == 1
    rec = captured[0]
    assert rec["preview_risk"] == "high"
    assert rec["preview_label"]  # non-empty plain-language description
    assert rec["preview_label"] != "send_email"  # mapped to a RU label, not raw


async def test_low_risk_action_preview() -> None:
    captured: list[dict[str, Any]] = []
    sandbox = InProcessSandbox(agent_runtime=_FakeRuntime(), audit_sink=captured.append)

    await sandbox.dispatch(DispatchRequest(agent_name="weather", action="get_weather"))

    assert captured[0]["preview_risk"] == "low"
