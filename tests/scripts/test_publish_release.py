"""Валидация версий и генерация манифеста publish_release (gh/git не вызываются)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import scripts.publish_release as pr
from scripts.publish_release import (
    build_manifest,
    collect_assets,
    validate_versions,
)


def _mk_dist(tmp: Path, ver: str) -> Path:
    d = tmp / "installer"
    d.mkdir()
    (d / f"KALI-Premium-Setup-{ver}.exe").write_bytes(b"exe-bytes")
    for i in (1, 2, 3):
        (d / f"KALI-Premium-Setup-{ver}-{i}.bin").write_bytes(b"bin" * i)
    return d


def _mk_repo(tmp: Path, tauri_ver: str, cargo_ver: str, iss_ver: str) -> Path:
    (tmp / "src-tauri").mkdir()
    (tmp / "scripts").mkdir()
    (tmp / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": tauri_ver}), encoding="utf-8"
    )
    (tmp / "src-tauri" / "Cargo.toml").write_text(
        f'[package]\nname = "kali-desktop"\nversion = "{cargo_ver}"\n', encoding="utf-8"
    )
    (tmp / "scripts" / "installer_premium.iss").write_text(
        f'#define AppVersion "{iss_ver}"\n', encoding="utf-8"
    )
    return tmp


def test_validate_passes_when_all_versions_match(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path, "1.0.1", "1.0.1", "1.0.1")
    dist = _mk_dist(tmp_path, "1.0.1")
    assert validate_versions(repo, dist) == "1.0.1"


@pytest.mark.parametrize("field", ["tauri", "cargo", "iss", "files"])
def test_validate_hard_fails_on_any_mismatch(tmp_path: Path, field: str) -> None:
    vers = {"tauri": "1.0.1", "cargo": "1.0.1", "iss": "1.0.1"}
    file_ver = "1.0.1"
    if field == "files":
        file_ver = "9.9.9"
    else:
        vers[field] = "9.9.9"
    repo = _mk_repo(tmp_path, vers["tauri"], vers["cargo"], vers["iss"])
    dist = _mk_dist(tmp_path, file_ver)
    with pytest.raises(SystemExit):
        validate_versions(repo, dist)


def test_collect_assets_requires_exactly_setup_plus_bins(tmp_path: Path) -> None:
    dist = _mk_dist(tmp_path, "1.0.1")
    assets = collect_assets(dist, "1.0.1")
    names = [a.name for a in assets]
    assert names[0] == "KALI-Premium-Setup-1.0.1.exe"  # exe первым (манифест-контракт)
    assert len(names) == 4
    # отсутствие слайса = hard fail
    (dist / "KALI-Premium-Setup-1.0.1-2.bin").unlink()
    with pytest.raises(SystemExit):
        collect_assets(dist, "1.0.1")


def test_build_manifest_has_correct_hashes_urls_sizes(tmp_path: Path) -> None:
    dist = _mk_dist(tmp_path, "1.0.1")
    assets = collect_assets(dist, "1.0.1")
    m = build_manifest("1.0.1", "notes", assets, pub_date="2026-07-20T12:00:00Z")
    assert m["version"] == "1.0.1"
    a0 = m["assets"][0]
    assert a0["name"] == "KALI-Premium-Setup-1.0.1.exe"
    assert a0["url"] == (
        "https://github.com/VasilyKolbenev/kali-ai-os/releases/download/"
        "v1.0.1/KALI-Premium-Setup-1.0.1.exe"
    )
    assert a0["sha256"] == hashlib.sha256(b"exe-bytes").hexdigest()
    assert a0["size"] == len(b"exe-bytes")
    assert len(m["assets"]) == 4


def _fake_gh(view_stdout: str, calls: list[list[str]]):
    """Canned subprocess.run: gh release view returns view_stdout; всё прочее — no-op.

    Records every command into `calls`; никакого реального gh не запускается.
    """
    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(cmd)
        if cmd[:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=view_stdout)
        return subprocess.CompletedProcess(cmd, 0, stdout="")
    return fake_run


def test_publish_recreates_stale_draft(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        pr.subprocess, "run",
        _fake_gh('{"isDraft": true, "tagName": "v1.0.1"}', calls),
    )
    pr.publish("1.0.1", "notes", [])
    # stale draft → delete (с --cleanup-tag) затем create
    delete = [c for c in calls if c[:3] == ["gh", "release", "delete"]]
    assert delete, "stale draft должен быть удалён"
    assert "--cleanup-tag" in delete[0]
    assert any(c[:3] == ["gh", "release", "create"] for c in calls)


def test_publish_idempotent_when_already_published(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        pr.subprocess, "run",
        _fake_gh('{"isDraft": false, "tagName": "v1.0.1"}', calls),
    )
    # Не-draft тот же тег → идемпотентный пропуск, без SystemExit
    pr.publish("1.0.1", "notes", [])
    assert all(c[:3] != ["gh", "release", "create"] for c in calls)
    assert len(calls) == 1  # только зонд view, ни create/upload/edit
