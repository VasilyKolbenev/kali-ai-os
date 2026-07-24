"""TDD (red-first) для scripts/release/installer_gate.py — C7 OPUS-201.

Wiring-политика инсталлятора: обязательный mode signed|internal, запрет internal
при distributable=true, .iss читает только premium_stage и подписывает Setup+
uninstaller. Проверки читают РЕАЛЬНЫЕ scripts/installer_premium.iss и
scripts/build_installer_premium.bat (правки этих файлов тест-верифицированы).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release import installer_gate as ig

ROOT = Path(__file__).resolve().parents[2]
ISS = ROOT / "scripts" / "installer_premium.iss"
BAT = ROOT / "scripts" / "build_installer_premium.bat"


# ── mode + internal/distributable forbid ────────────────────────────────────
def test_resolve_mode_signed_ok() -> None:
    assert ig.resolve_build_mode("signed", distributable=True) == "signed"


def test_resolve_mode_internal_ok_when_not_distributable() -> None:
    assert ig.resolve_build_mode("internal", distributable=False) == "internal"


def test_resolve_mode_internal_forbidden_when_distributable() -> None:
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.resolve_build_mode("internal", distributable=True)
    assert "INTERNAL_DISTRIBUTABLE" in str(exc.value)


@pytest.mark.parametrize("bad", [None, "", "release", "prod"])
def test_resolve_mode_rejects_unknown(bad) -> None:
    with pytest.raises(Exception) as exc:
        ig.resolve_build_mode(bad, distributable=False)
    assert "MODE" in str(exc.value)


# ── read_distributable (fail-closed) ────────────────────────────────────────
def test_read_distributable_true(tmp_path: Path) -> None:
    p = tmp_path / "release-status.json"
    p.write_text(json.dumps({"distributable": True}), encoding="utf-8")
    assert ig.read_distributable(p) is True


def test_read_distributable_false(tmp_path: Path) -> None:
    p = tmp_path / "release-status.json"
    p.write_text(json.dumps({"distributable": False}), encoding="utf-8")
    assert ig.read_distributable(p) is False


def test_read_distributable_missing_fails(tmp_path: Path) -> None:
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.read_distributable(tmp_path / "nope.json")
    assert "STATUS_MISSING" in str(exc.value)


@pytest.mark.parametrize("val", ["true", 1, None])
def test_read_distributable_non_bool_fails(tmp_path: Path, val) -> None:
    p = tmp_path / "release-status.json"
    p.write_text(json.dumps({"distributable": val}), encoding="utf-8")
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.read_distributable(p)
    assert "STATUS_SCHEMA" in str(exc.value)


# ── .iss policy over crafted text ───────────────────────────────────────────
def test_assert_iss_stage_only_rejects_external_source() -> None:
    bad = 'Source: "..\\scripts\\install-webview2.ps1"; DestDir: "{app}"\n'
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_OUTSIDE_STAGE" in str(exc.value)


def test_assert_iss_stage_only_accepts_stage_source() -> None:
    ok = 'Source: "..\\dist_premium\\premium_stage\\*"; DestDir: "{app}"\n'
    ig.assert_iss_stage_only(ok)  # не поднимает


def test_assert_iss_signs_requires_setup_and_uninstaller() -> None:
    with pytest.raises(ig.InstallerGateError):
        ig.assert_iss_signs_setup_and_uninstaller("[Setup]\nAppName=x\n")


# ── REAL files: the .iss/.bat edits are test-verified ───────────────────────
def test_real_iss_files_are_stage_only() -> None:
    ig.assert_iss_stage_only(ISS.read_text(encoding="utf-8"))


def test_real_iss_signs_setup_and_uninstaller() -> None:
    ig.assert_iss_signs_setup_and_uninstaller(ISS.read_text(encoding="utf-8"))


def test_real_bat_requires_mode_and_delegates_to_gates() -> None:
    text = BAT.read_text(encoding="utf-8")
    # mode is a mandatory arg
    assert "signed" in text and "internal" in text
    # signing/mode decisions delegated to the tested Python gates
    assert "installer_gate" in text or "signing_gate" in text
    # post-sign verification wired (no silent unsigned "success")
    assert "verify" in text.lower()


# ── CLI main() (consumed by the .bat) ───────────────────────────────────────
def test_main_resolve_mode_prints_mode(tmp_path: Path, capsys) -> None:
    status = tmp_path / "release-status.json"
    status.write_text(json.dumps({"distributable": False}), encoding="utf-8")
    rc = ig.main(["resolve-mode", "internal", str(status)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "internal"


def test_main_resolve_mode_forbidden_exits_nonzero(tmp_path: Path) -> None:
    status = tmp_path / "release-status.json"
    status.write_text(json.dumps({"distributable": True}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        ig.main(["resolve-mode", "internal", str(status)])
    assert exc.value.code != 0


def test_main_mark_internal_renames(tmp_path: Path) -> None:
    setup = tmp_path / "KALI-Premium-Setup-1.0.0-rc3.exe"
    setup.write_bytes(b"SETUP")
    rc = ig.main(["mark-internal", str(setup), "1.0.0-rc3"])
    assert rc == 0
    assert (tmp_path / "KALI-Premium-Setup-1.0.0-rc3-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.exe").is_file()
    assert (tmp_path / "INTERNAL-UNSIGNED.txt").is_file()
