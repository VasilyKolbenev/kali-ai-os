"""Security tests for kernel.skills.installer — untrusted-input hardening.

These cover the Windows prod-readiness C11 cluster: catalog tarballs and shared
bundles are UNTRUSTED. They must never write outside their staging dir, never
exceed a size cap (decompression bomb), and shared bundles must not carry
executable ``scripts/``.
"""

from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

import pytest

from kernel.skills import installer as installer_mod
from kernel.skills.installer import (
    InstallError,
    _download_repo_subtree,
    install_from_bundle,
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


def _bundle_b64_from_bytes(raw: bytes) -> str:
    """base64url-encode a raw .tar.gz for install_from_bundle."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_bundle_size_cap_rejects_oversized_member(
    tmp_path: Path, monkeypatch
) -> None:
    """A member whose (declared) size exceeds the cap is rejected before
    extractall — a decompression bomb never inflates onto disk.

    The cap is lowered so a valid, tiny tar still trips it; this keeps the tar
    well-formed (real bytes) while exercising the guard's per-member/total check.
    """
    monkeypatch.setattr(installer_mod, "_MAX_BUNDLE_UNCOMPRESSED_BYTES", 16)

    payload = b"x" * 64  # 64 bytes > 16-byte cap
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="demo-agent/SKILL.md")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    data = _bundle_b64_from_bytes(buf.getvalue())

    called = {"extractall": False}
    real_extractall = tarfile.TarFile.extractall

    def _spy_extractall(self, *a, **k):  # noqa: ANN001, ANN202
        called["extractall"] = True
        return real_extractall(self, *a, **k)

    monkeypatch.setattr(tarfile.TarFile, "extractall", _spy_extractall)

    result = install_from_bundle(data, target_dir=tmp_path / "installed")
    assert not result.ok
    assert result.error == "Bundle too large"
    assert called["extractall"] is False
