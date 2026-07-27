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


def test_assert_iss_rejects_toplevel_include() -> None:
    # H5: обычное место ISPP-#include — ВНЕ [Files]; он может принести вторую секцию
    # [Files], которой гейт не видит, и verify-iss всё равно скажет «ok».
    text = ('#include "extra-files.iss"\n[Setup]\nAppName=x\n\n[Files]\n'
            'Source: "..\\dist_premium\\premium_stage\\*"; DestDir: "{app}"\n')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(text)
    assert "ISS_UNRESOLVED_INCLUDE" in str(exc.value)


def test_assert_iss_rejects_unresolvable_include_in_files() -> None:
    # ISPP #include подтягивает записи, которых парсер не видит → fail-closed
    bad = _files('#include "extra-files.iss"',
                 'Source: "..\\dist_premium\\premium_stage\\*"; DestDir: "{app}"')
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_stage_only(bad)
    assert "ISS_UNRESOLVED_INCLUDE" in str(exc.value)


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


# ── H6-4: только АКТИВНЫЕ директивы, с учётом guard'ов ──────────────────────
def _signed_iss(signtool: str = "SignTool=kali",
                uninst: str = "SignedUninstaller=yes",
                naming: str = "OutputBaseFilename=x-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE") -> str:
    return ("[Setup]\nAppName=x\n"
            "#ifdef SignSetup\n" + signtool + "\n" + uninst + "\n#endif\n"
            "#ifdef Internal\n" + naming + "\n#endif\n")


def test_commented_out_signeduninstaller_is_not_active() -> None:
    text = _signed_iss(uninst="; SignedUninstaller=yes")
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_signs_setup_and_uninstaller(text)
    assert "NO_UNINSTALLER_SIGN" in str(exc.value)


def test_commented_out_signtool_is_not_active() -> None:
    text = _signed_iss(signtool="; SignTool=kali")
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_signs_setup_and_uninstaller(text)
    assert "NO_SETUP_SIGN" in str(exc.value)


def test_commented_out_internal_naming_is_not_active() -> None:
    text = _signed_iss(naming="; OutputBaseFilename=x-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE")
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.assert_iss_internal_naming(text)
    assert "NO_INTERNAL_NAMING" in str(exc.value)


def test_active_directives_normalize_whitespace_and_case() -> None:
    text = ("[Setup]\n#ifdef SignSetup\n   signtool   =   kali  \n"
            "\tSignedUninstaller\t=\tYES\t\n#endif\n")
    ig.assert_iss_signs_setup_and_uninstaller(text)  # не поднимает


def test_signing_directives_outside_the_guard_are_refused() -> None:
    # незагарденные директивы применились бы и к internal-сборке
    text = "[Setup]\nSignTool=kali\nSignedUninstaller=yes\n"
    with pytest.raises(ig.InstallerGateError):
        ig.assert_iss_signs_setup_and_uninstaller(text)


# ── H6-4: подписанный uninsNNN.exe — обязательная проверка live acceptance ──
def test_verify_installed_uninstaller_requires_valid_exact_timestamped(tmp_path: Path) -> None:
    from scripts.release import signing_gate as sg
    root = tmp_path / "app"
    root.mkdir()
    (root / "unins000.exe").write_bytes(b"MZ")
    thumb = "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2"
    good = {"status": "Valid", "thumbprint": thumb, "timestamped": True}
    assert ig.verify_installed_uninstaller(root, expected_thumbprint=thumb,
                                           inspector=lambda p: dict(good)) == 1
    for broken in ({"status": "HashMismatch"}, {"thumbprint": "DEAD"}, {"timestamped": False}):
        report = dict(good, **broken)
        with pytest.raises(sg.SigningGateError):
            ig.verify_installed_uninstaller(root, expected_thumbprint=thumb,
                                            inspector=lambda p, r=report: dict(r))


def test_verify_installed_uninstaller_requires_one_to_exist(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.verify_installed_uninstaller(root, expected_thumbprint="A" * 40,
                                        inspector=lambda p: {})
    assert "UNINSTALLER_MISSING" in str(exc.value)


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


# ── H6-5: точный транзакционный вывод инсталлятора ──────────────────────────
def _mk_output(dir_: Path, version: str = "1.0.0-rc3", slices: int = 2) -> str:
    dir_.mkdir(parents=True, exist_ok=True)
    setup = f"KALI-Premium-Setup-{version}.exe"
    (dir_ / setup).write_bytes(b"SETUP")
    for i in range(1, slices + 1):
        (dir_ / f"KALI-Premium-Setup-{version}-{i}.bin").write_bytes(f"S{i}".encode())
    return setup


def test_collect_installer_artifacts_is_exact_and_contiguous(tmp_path: Path) -> None:
    setup = _mk_output(tmp_path / "out")
    manifest = ig.collect_installer_artifacts(tmp_path / "out", setup)
    assert [f["name"] for f in manifest["files"]] == [
        setup, f"{setup[:-4]}-1.bin", f"{setup[:-4]}-2.bin"]
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])


def test_collect_installer_artifacts_rejects_a_stale_noncontiguous_slice(tmp_path: Path) -> None:
    out = tmp_path / "out"
    setup = _mk_output(out, slices=2)
    (out / f"{setup[:-4]}-3.bin").write_bytes(b"STALE-FROM-A-BIGGER-BUILD")
    # -3 сразу после -2 непрерывен; дыра появляется, если пропал -2
    (out / f"{setup[:-4]}-2.bin").unlink()
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.collect_installer_artifacts(out, setup)
    assert "NONCONTIGUOUS_SLICES" in str(exc.value)


def test_collect_installer_artifacts_rejects_a_stray_file(tmp_path: Path) -> None:
    out = tmp_path / "out"
    setup = _mk_output(out)
    (out / "leftover.tmp").write_bytes(b"X")
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.collect_installer_artifacts(out, setup)
    assert "STRAY_OUTPUT" in str(exc.value)


def test_load_installer_manifest_detects_a_tampered_artifact(tmp_path: Path) -> None:
    out = tmp_path / "out"
    setup = _mk_output(out)
    ig.write_installer_manifest(out, setup)
    (out / f"{setup[:-4]}-1.bin").write_bytes(b"TAMPERED")
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.load_installer_manifest(out)
    assert "ARTIFACT_HASH_MISMATCH" in str(exc.value)


def test_load_installer_manifest_detects_a_slice_appearing_later(tmp_path: Path) -> None:
    out = tmp_path / "out"
    setup = _mk_output(out, slices=2)
    ig.write_installer_manifest(out, setup)
    (out / f"{setup[:-4]}-3.bin").write_bytes(b"STALE")  # подложен ПОСЛЕ печати
    with pytest.raises(ig.InstallerGateError) as exc:
        ig.load_installer_manifest(out)
    assert "STRAY_OUTPUT" in str(exc.value)


def test_promote_installer_output_replaces_the_previous_dir(tmp_path: Path) -> None:
    dist = tmp_path / "dist_premium"
    old = dist / "installer"
    old.mkdir(parents=True)
    (old / "KALI-Premium-Setup-0.9.9.exe").write_bytes(b"OLD")
    (old / "KALI-Premium-Setup-0.9.9-9.bin").write_bytes(b"STALE-SLICE")
    nxt = dist / "installer.next-1"
    setup = _mk_output(nxt)
    ig.write_installer_manifest(nxt, setup)
    final = ig.promote_installer_output(dist, nxt)
    assert final == old and not nxt.exists()
    assert not (final / "KALI-Premium-Setup-0.9.9-9.bin").exists()  # stale не пережил
    ig.load_installer_manifest(final)


def test_promote_refuses_an_unsealed_output(tmp_path: Path) -> None:
    dist = tmp_path / "dist_premium"
    old = dist / "installer"
    old.mkdir(parents=True)
    (old / "keep.txt").write_bytes(b"LASTGOOD")
    nxt = dist / "installer.next-1"
    _mk_output(nxt)  # без INSTALLER_ARTIFACTS.json
    with pytest.raises(ig.InstallerGateError):
        ig.promote_installer_output(dist, nxt)
    assert (old / "keep.txt").read_bytes() == b"LASTGOOD"


def test_real_bat_builds_into_a_next_output_dir_and_promotes() -> None:
    text = BAT.read_text(encoding="utf-8")
    assert "installer.next-" in text, ".bat обязан собирать в чистый next-каталог"
    iscc_line = next(ln for ln in text.splitlines() if "%ISCC%" in ln and ".iss" in ln)
    assert "/O%OUTNEXT%" in iscc_line, "ISCC обязан писать в next-каталог, а не поверх live"
    seal, promote, iscc = (text.find("seal-output"), text.find("promote-output"),
                           text.find("%ISCC%"))
    assert iscc != -1 and seal > iscc and promote > seal


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


# ── H4/D3: .bat берёт signtool из ЕДИНОГО python-резолвера, guard ДО compose ─
def test_main_resolve_signtool_cli(monkeypatch, capsys, tmp_path: Path) -> None:
    from scripts.release import signing_gate
    kit = tmp_path / "10.0.26100.0" / "x64"
    kit.mkdir(parents=True)
    (kit / "signtool.exe").write_bytes(b"MZ")
    monkeypatch.setattr(signing_gate, "_KITS_ROOT", tmp_path)
    monkeypatch.setattr(signing_gate.shutil, "which", lambda name: None)
    monkeypatch.delenv("KALI_SIGN_SIGNTOOL", raising=False)
    assert ig.main(["resolve-signtool"]) == 0
    assert capsys.readouterr().out.strip() == str(kit / "signtool.exe")


def test_main_resolve_signtool_exits_nonzero_when_absent(monkeypatch, tmp_path: Path) -> None:
    from scripts.release import signing_gate
    monkeypatch.setattr(signing_gate, "_KITS_ROOT", tmp_path)
    monkeypatch.setattr(signing_gate.shutil, "which", lambda name: None)
    monkeypatch.delenv("KALI_SIGN_SIGNTOOL", raising=False)
    with pytest.raises(SystemExit) as exc:
        ig.main(["resolve-signtool"])
    assert exc.value.code != 0


def test_real_bat_resolves_signtool_via_the_python_gate() -> None:
    # .bat не имеет права держать СВОЙ список путей: он видел только неверсионный
    # bin\x64 и не находил signtool там, где его находит python.
    text = BAT.read_text(encoding="utf-8")
    assert "installer_gate resolve-signtool" in text
    assert "Windows Kits" not in text, "у .bat не должно быть собственного списка путей"


def test_real_bat_aborts_signed_without_signtool_before_compose() -> None:
    # иначе signed-билд подписывает EXE и копирует ~9 ГБ, а затем падает
    text = BAT.read_text(encoding="utf-8")
    guard = text.find("signed build requires signtool.exe")
    compose = text.find("scripts.release.compose_cli")
    assert guard != -1 and compose != -1
    assert guard < compose, "abort обязан быть ДО compose"


def test_real_bat_documents_the_signtool_env_var() -> None:
    assert "KALI_SIGN_SIGNTOOL" in BAT.read_text(encoding="utf-8")[:2000]


def test_real_bat_exports_signtool_to_the_composer(tmp_path: Path) -> None:
    # H3.1: .bat обязан передать разрешённый signtool композеру через
    # KALI_SIGN_SIGNTOOL ДО compose, иначе резолверы разойдутся.
    text = BAT.read_text(encoding="utf-8")
    export = text.find('set "KALI_SIGN_SIGNTOOL=%SIGNTOOL%"')
    compose = text.find("scripts.release.compose_cli")
    assert export != -1, "the .bat never exports KALI_SIGN_SIGNTOOL"
    assert compose != -1 and export < compose, "export must happen BEFORE compose"


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
