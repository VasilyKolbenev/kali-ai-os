"""TDD (red-first) для scripts/release/installer_gate.py — C7 OPUS-201.

Wiring-политика инсталлятора: обязательный mode signed|internal, запрет internal
при distributable=true, .iss читает только premium_stage и подписывает Setup+
uninstaller. Проверки читают РЕАЛЬНЫЕ scripts/installer_premium.iss и
scripts/build_installer_premium.bat (правки этих файлов тест-верифицированы).
"""
from __future__ import annotations

import json
import subprocess
import sys
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


# ── .iss policy over crafted text (H2.3: реальный разбор секции [Files]) ────
def _files(*lines: str) -> str:
    """Минимальный .iss с секцией [Files] из переданных строк."""
    return "[Setup]\nAppName=x\n\n[Files]\n" + "".join(f"{ln}\n" for ln in lines) + "\n[Icons]\n"


def test_assert_iss_stage_only_rejects_external_source() -> None:
    bad = _files('Source: "..\\scripts\\install-webview2.ps1"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_OUTSIDE_STAGE" in str(exc.value)


def test_assert_iss_stage_only_accepts_stage_source() -> None:
    ok = _files('Source: "..\\dist_premium\\premium_stage\\*"; DestDir: "{app}"')
    ig.assert_iss_stage_only(ok)  # не поднимает


def test_assert_iss_requires_a_files_section() -> None:
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only("[Setup]\nAppName=x\n")
    assert "ISS_NO_FILES_SECTION" in str(exc.value)


def test_assert_iss_requires_at_least_one_source() -> None:
    # пустая [Files] = инсталлятор без содержимого; «нет Source» не должно быть «ok»
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(_files('; only a comment'))
    assert "ISS_NO_SOURCE" in str(exc.value)


def test_assert_iss_rejects_unquoted_source() -> None:
    bad = _files('Source: ..\\scripts\\install-webview2.ps1; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_UNQUOTED" in str(exc.value)


def test_assert_iss_rejects_premium_stage_substring_trick() -> None:
    # «premium_stage» как ПОДСТРОКА соседнего каталога больше не проходит
    bad = _files('Source: "..\\dist_premium\\premium_stage_evil\\*"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_OUTSIDE_STAGE" in str(exc.value)


def test_assert_iss_rejects_traversal_back_out_of_stage() -> None:
    bad = _files('Source: "..\\dist_premium\\premium_stage\\..\\..\\scripts\\*"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_OUTSIDE_STAGE" in str(exc.value)


def test_assert_iss_rejects_absolute_source() -> None:
    bad = _files('Source: "C:\\evil\\payload.dll"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_ABSOLUTE" in str(exc.value)


def test_assert_iss_rejects_stage_root_itself_without_content() -> None:
    # «..\dist_premium\premium_stage» без вложенного пути — не файловый источник
    bad = _files('Source: "..\\dist_premium\\premium_stage"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_SOURCE_OUTSIDE_STAGE" in str(exc.value)


def test_assert_iss_rejects_one_bad_source_among_good() -> None:
    bad = _files('Source: "..\\dist_premium\\premium_stage\\*"; DestDir: "{app}"',
                 'Source: "..\\models\\secret.bin"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError):
        ig.assert_iss_stage_only(bad)


def test_assert_iss_handles_line_continuations() -> None:
    ok = _files('Source: "..\\dist_premium\\premium_stage\\*"; DestDir: "{app}"; \\',
                '    Flags: recursesubdirs createallsubdirs ignoreversion')
    ig.assert_iss_stage_only(ok)  # продолжение строки не ломает разбор


def test_assert_iss_ignores_sources_outside_files_section() -> None:
    # Source в другой секции не является [Files]-входом и не заменяет обязательный
    text = ("[Files]\n; nothing here\n\n[Icons]\n"
            'Source: "..\\dist_premium\\premium_stage\\*"\n')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(text)
    assert "ISS_NO_SOURCE" in str(exc.value)


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


# ── F4#5: real cmd.exe invocation — bad mode = clean nonzero reason (no syntax err) ─
def _run_bat(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["cmd", "/c", str(BAT), *extra],
                          capture_output=True, text=True, cwd=str(ROOT))


def test_bat_cmd_invocation_rejects_missing_mode() -> None:
    if sys.platform != "win32":
        pytest.skip("cmd.exe only on Windows")
    proc = _run_bat()
    out = (proc.stdout + proc.stderr).lower()
    assert proc.returncode != 0
    assert "mode required" in out
    assert "was unexpected" not in out and "syntax" not in out  # not a batch syntax error


def test_bat_cmd_invocation_rejects_unknown_mode() -> None:
    if sys.platform != "win32":
        pytest.skip("cmd.exe only on Windows")
    proc = _run_bat("bogusmode")
    out = (proc.stdout + proc.stderr).lower()
    assert proc.returncode != 0
    assert "mode" in out
    assert "was unexpected" not in out and "syntax" not in out


def test_bat_cmd_invocation_accepts_valid_mode_past_gate() -> None:
    # G1: a VALID mode (internal, release-status distributable=false) must parse and
    # PASS the mode gate — the for/f that runs installer_gate must actually execute.
    # Execution then reaches the backend-not-built check, NOT "rejected build mode".
    if sys.platform != "win32":
        pytest.skip("cmd.exe only on Windows")
    proc = _run_bat("internal")
    out = (proc.stdout + proc.stderr).lower()
    assert "rejected build mode" not in out       # the gate parsed + accepted it
    assert "build mode: internal" in out          # the validated mode was set (for/f ran)


def test_main_write_marker(tmp_path: Path) -> None:
    # F4#7: naming is done by ISCC OutputBaseFilename — the CLI only drops the marker
    rc = ig.main(["write-marker", str(tmp_path), "1.0.0-rc3"])
    assert rc == 0
    assert (tmp_path / "INTERNAL-UNSIGNED.txt").is_file()


def test_real_iss_internal_naming() -> None:
    ig.assert_iss_internal_naming(ISS.read_text(encoding="utf-8"))


def test_real_iss_passes_verify_iss() -> None:
    ig.verify_iss(ISS.read_text(encoding="utf-8"))


def test_main_verify_iss_ok() -> None:
    assert ig.main(["verify-iss", str(ISS)]) == 0
