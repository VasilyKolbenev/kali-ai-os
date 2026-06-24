"""The dry-run preview survives the real AuditLog write -> query round-trip.

Proves the full backend chain the Activity view depends on: a sandbox dispatch
enriches the record with preview fields, AuditLog stores them in the `extra`
JSON column, and query() returns them so the UI can parse and render them.
"""

import json
from pathlib import Path
from typing import Any

from kernel.sandbox.audit import AuditLog
from kernel.sandbox.backend import DispatchRequest, InProcessSandbox


class _FakeRuntime:
    async def dispatch(self, name: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


async def test_preview_survives_audit_roundtrip(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.db")
    sandbox = InProcessSandbox(agent_runtime=_FakeRuntime(), audit_sink=audit.write)

    await sandbox.dispatch(
        DispatchRequest(agent_name="email", action="send_email", args={"to": "a@b.com"})
    )

    rows = audit.query(limit=1)
    assert len(rows) == 1
    extra = json.loads(rows[0]["extra"])
    assert extra["preview_label"]  # plain-language description persisted
    assert extra["preview_risk"] == "high"
