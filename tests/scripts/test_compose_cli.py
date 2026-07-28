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
    # G5: the SoT integrity manifest the composer verifies before copy
    _mpath = dist / "premium_assets" / "PREMIUM_ASSETS.sha256.json"
    _mpath.write_text(json.dumps({"entries": stage_policy.file_content_hashes(sot)}),
                      encoding="utf-8")
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install-webview2.ps1").write_bytes(b"PS")
    if with_receipts:
        import hashlib

        from scripts.release import asset_bootstrap as _ab
        _sot, _manifest = _ab.sot_paths(dist)
        rc.write_receipt(backend, dist / "kali-backend.BUILD_RECEIPT.json",
                         git_sha="a" * 40, version="1.0.0-rc3", dirty=False,
                         build_kind="pyinstaller-onedir", toolchain="py3.12",
                         asset_manifest_sha256=hashlib.sha256(
                             _manifest.read_bytes()).hexdigest())
        rc.write_receipt(tauri / "kali-desktop.exe",
                         tauri / "kali-desktop.exe.BUILD_RECEIPT.json",
                         git_sha="a" * 40, version="1.0.0-rc3", dirty=False,
                         build_kind="tauri-release", toolchain="rust")
    return repo, dist, tauri


def test_compose_cli_composes_from_assembled_paths(tmp_path: Path) -> None:
    repo, dist, tauri = _layout(tmp_path)
    stage = cc.compose(repo, dist, tauri, mode="internal", version="1.0.0-rc3",
                       git_sha="a" * 40, materializer=lambda p: None,
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
                   git_sha="a" * 40, materializer=lambda p: None,
                   signer=lambda p, m: None, token="1")
    assert "RECEIPT_MISSING" in str(exc.value)


# ── F4: no owner placeholders + signed preflight BEFORE compose ─────────────
def test_compose_cli_has_no_owner_literals() -> None:
    src = Path(cc.__file__).read_text(encoding="utf-8")
    assert "__owner" not in src


def test_build_signing_internal_is_noop() -> None:
    signer = cc.build_signing("internal", env={})
    signer(Path("."), "internal")  # no-op, no raise


def test_build_signing_signed_fail_closed_without_contract() -> None:
    from scripts.release import signing_gate
    with pytest.raises(signing_gate.SigningGateError):
        cc.build_signing("signed", env={})  # fail-closed BEFORE any compose/stage mutation


def test_build_signing_signed_ok_via_windows_kits_fallback(monkeypatch, tmp_path: Path) -> None:
    # H3.2: signtool отсутствует в PATH, но лежит в Windows Kits — signed preflight
    # обязан пройти (композер и .bat используют один резолвер).
    from scripts.release import signing_gate
    kit = tmp_path / "10.0.22621.0" / "x64"
    kit.mkdir(parents=True)
    (kit / "signtool.exe").write_bytes(b"MZ")
    monkeypatch.setattr(signing_gate, "_KITS_ROOT", tmp_path)
    monkeypatch.setattr(signing_gate.shutil, "which", lambda name: None)
    monkeypatch.setattr(signing_gate, "probe_signtool", lambda s, **k: None)
    signer = cc.build_signing("signed", env={
        "KALI_SIGN_THUMBPRINT": "B1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B3",
        "KALI_SIGN_EXPECTED_THUMBPRINT": "A1B2C3D4" * 5,
    })
    assert callable(signer)


def test_build_signing_signed_fails_when_signtool_nowhere(monkeypatch, tmp_path: Path) -> None:
    from scripts.release import signing_gate
    monkeypatch.setattr(signing_gate, "_KITS_ROOT", tmp_path)
    monkeypatch.setattr(signing_gate.shutil, "which", lambda name: None)
    with pytest.raises(signing_gate.SigningGateError) as exc:
        cc.build_signing("signed", env={
            "KALI_SIGN_THUMBPRINT": "B1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B3",
            "KALI_SIGN_EXPECTED_THUMBPRINT": "A1B2C3D4",
        })
    assert "SIGNTOOL" in str(exc.value)


def test_build_signing_signed_ok_with_full_contract(tmp_path: Path) -> None:
    # H7-6: проба требует, чтобы инструмент опознавался как SignTool
    tool = tmp_path / "signtool.cmd"
    tool.write_text("@echo off\r\necho SignTool Error: none.\r\n"
                    "echo Commands: sign timestamp verify\r\n", encoding="ascii")
    signer = cc.build_signing("signed", env={
        "KALI_SIGN_THUMBPRINT": "B1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B3",
        "KALI_SIGN_EXPECTED_THUMBPRINT": "A1B2C3D4" * 5,
        "KALI_SIGN_SIGNTOOL": str(tool),
    })
    assert callable(signer)


def test_build_signing_signed_rejects_a_fake_signtool(tmp_path: Path) -> None:
    # H6-6: is_file() мало — подделка обязана упасть в preflight, а не при подписи
    from scripts.release import signing_gate
    fake = tmp_path / "signtool.exe"
    fake.write_bytes(b"not a real PE image")
    with pytest.raises(signing_gate.SigningGateError) as exc:
        cc.build_signing("signed", env={
            "KALI_SIGN_THUMBPRINT": "B1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B3",
            "KALI_SIGN_EXPECTED_THUMBPRINT": "A1B2C3D4" * 5,
            "KALI_SIGN_SIGNTOOL": str(fake),
        })
    assert "SIGNTOOL" in str(exc.value)


def test_build_signing_signed_rejects_a_missing_pfx(tmp_path: Path) -> None:
    import sys as _sys

    from scripts.release import signing_gate
    with pytest.raises(signing_gate.SigningGateError) as exc:
        cc.build_signing("signed", env={
            "KALI_SIGN_PFX": str(tmp_path / "nope.pfx"),
            "KALI_SIGN_EXPECTED_THUMBPRINT": "A1B2C3D4" * 5,
            "KALI_SIGN_SIGNTOOL": _sys.executable,
        })
    assert "SELECTOR" in str(exc.value)


def test_build_signing_signed_rejects_stale_signtool_path(tmp_path: Path) -> None:
    # H5: явный, но несуществующий путь обязан упасть в preflight, а не при подписи
    from scripts.release import signing_gate
    with pytest.raises(signing_gate.SigningGateError):
        cc.build_signing("signed", env={
            "KALI_SIGN_THUMBPRINT": "B1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B3",
            "KALI_SIGN_EXPECTED_THUMBPRINT": "A1B2C3D4",
            "KALI_SIGN_SIGNTOOL": str(tmp_path / "moved-sdk" / "signtool.exe"),
        })


# ── G5: premium_assets SoT integrity is load-bearing (drift stops compose) ──
def test_compose_cli_stops_on_sot_drift(tmp_path: Path) -> None:
    from scripts.release import asset_bootstrap as ab
    repo, dist, tauri = _layout(tmp_path)
    (dist / "premium_assets" / "models" / "model.bin").write_bytes(b"DRIFTED")  # after bootstrap
    with pytest.raises(ab.BootstrapError) as exc:
        cc.compose(repo, dist, tauri, mode="internal", version="1.0.0-rc3",
                   git_sha="a" * 40, materializer=lambda p: None,
                   signer=lambda p, m: None, token="1")
    assert "SOT_DRIFT" in str(exc.value)
