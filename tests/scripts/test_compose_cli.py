"""TDD (red-first) для scripts/release/compose_cli.py — C7 OPUS-103.

Тонкая обёртка, которой .bat заменяет аддитивный robocopy /E: собирает пути
входов/receipts и зовёт транзакционный композер. Fail-closed без receipt.
Реальные materializer/signer инъектируются (никакого multi-GB билда).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release import compose_cli as cc
from scripts.release import receipts as rc
from scripts.release import stage_policy


def _layout(tmp_path: Path, *, with_receipts: bool = True) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    dist = repo / "dist_premium"
    tauri = repo / "src-tauri" / "target" / "release"
    backend = dist / "kali-backend"
    (backend / "_internal").mkdir(parents=True)
    (backend / "kali-backend.exe").write_bytes(b"BE")
    (backend / "_internal" / "lib.zip").write_bytes(b"L")
    tauri.mkdir(parents=True)
    (tauri / "kali-desktop.exe").write_bytes(b"DT")
    sot = dist / "premium_assets" / "models"
    (sot / "ffmpeg").mkdir(parents=True)
    (sot / "model.bin").write_bytes(b"W")
    (sot / "ggml-base.bin").write_bytes(b"DEAD")
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install-webview2.ps1").write_bytes(b"PS")
    if with_receipts:
        rc.write_receipt(backend, dist / "kali-backend.BUILD_RECEIPT.json",
                         git_sha="s" * 40, version="1.0.0-rc3", dirty=False,
                         build_kind="pyinstaller-onedir", toolchain="py3.12")
        rc.write_receipt(tauri / "kali-desktop.exe",
                         tauri / "kali-desktop.exe.BUILD_RECEIPT.json",
                         git_sha="s" * 40, version="1.0.0-rc3", dirty=False,
                         build_kind="tauri-release", toolchain="rust")
    return repo, dist, tauri


def test_compose_cli_composes_from_assembled_paths(tmp_path: Path) -> None:
    repo, dist, tauri = _layout(tmp_path)
    stage = cc.compose(repo, dist, tauri, mode="internal", version="1.0.0-rc3",
                       git_sha="s" * 40, materializer=lambda p: None,
                       signer=lambda p, m: None, token="1")
    assert stage == dist / "premium_stage"
    assert (stage / "install-webview2.ps1").read_bytes() == b"PS"
    assert (stage / "kali-backend" / "kali-backend.exe").read_bytes() == b"BE"
    assert (stage / "models" / "model.bin").read_bytes() == b"W"
    assert not (stage / "models" / "ggml-base.bin").exists()  # dead weight excluded
    manifest = json.loads((stage / stage_policy.MANIFEST_NAME).read_text(encoding="utf-8"))
    stage_policy.verify_manifest(stage, manifest)


def test_compose_cli_fail_closed_without_receipt(tmp_path: Path) -> None:
    repo, dist, tauri = _layout(tmp_path, with_receipts=False)
    with pytest.raises(rc.ReceiptError) as exc:
        cc.compose(repo, dist, tauri, mode="internal", version="1.0.0-rc3",
                   git_sha="s" * 40, materializer=lambda p: None,
                   signer=lambda p, m: None, token="1")
    assert "RECEIPT_MISSING" in str(exc.value)
