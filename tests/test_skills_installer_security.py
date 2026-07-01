"""Security tests for kernel.skills.installer — untrusted-input hardening.

These cover the Windows prod-readiness C11 cluster: catalog tarballs and shared
bundles are UNTRUSTED. They must never write outside their staging dir, never
exceed a size cap (decompression bomb), and shared bundles must not carry
executable ``scripts/``.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from kernel.skills.installer import (
    InstallError,
    _download_repo_subtree,
)


def _tar_gz_bytes(members: list[tuple[str, bytes]]) -> bytes:
    """Build an in-memory .tar.gz from (name, content) pairs."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class _FakeResponse:
    """Minimal stand-in for a streamed requests.Response."""

    def __init__(self, raw: bytes, status_code: int = 200) -> None:
        self._raw = raw
        self.status_code = status_code

    def iter_content(self, chunk_size: int = 65536):  # noqa: ANN201
        for i in range(0, len(self._raw), chunk_size):
            yield self._raw[i : i + chunk_size]


def test_catalog_tar_traversal_rejected(tmp_path: Path, monkeypatch) -> None:
    """A member resolving outside the staging subtree raises InstallError and
    writes nothing outside staging."""
    sentinel = tmp_path / "pwned.py"
    raw = _tar_gz_bytes(
        [
            ("repo-main/skills/x/ok.py", b"# legit\n"),
            ("repo-main/skills/x/../../../../pwned.py", b"# evil\n"),
        ]
    )
    monkeypatch.setattr(
        "kernel.skills.installer.requests.get",
        lambda *a, **k: _FakeResponse(raw),
    )

    dest = tmp_path / "staging"
    with pytest.raises(InstallError):
        _download_repo_subtree("o", "repo", "main", "skills/x", dest)

    assert not sentinel.exists()
    # Nothing escaped the staging dir.
    assert not (tmp_path / "pwned.py").exists()
