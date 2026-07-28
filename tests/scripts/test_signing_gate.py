"""TDD (red-first) для scripts/release/signing_gate.py — C4 OPUS-201.

Fail-closed signing policy. Реальный signtool/cert не запускаются: runner
инъектируется. Матрица mode/selector/signer/timestamp; reason-token в исключении.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release import signing_gate as sg

SIGNER = "KALI Labs LLC"
THUMB = "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2"  # expected signer thumbprint
SELECTOR_THUMB = "B1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B3"  # store/HSM selector
TS = "http://timestamp.digicert.com"


def _write_tool(path: Path, lines: list[str]) -> str:
    """A runnable .cmd standing in for a signing tool (no real SDK in tests)."""
    body = "@echo off\r\n" + "".join(f"echo {line}\r\n" for line in lines)
    path.write_text(body, encoding="ascii")
    return str(path)


@pytest.fixture
def fake_signtool(tmp_path: Path) -> str:
    """Behaves like SignTool: its banner names the tool and its verbs."""
    return _write_tool(tmp_path / "signtool.cmd",
                       ["SignTool Error: No file is specified.",
                        "Commands: sign timestamp verify catdb remove"])


@pytest.fixture
def not_signtool(tmp_path: Path) -> str:
    """Launches perfectly happily and is not SignTool at all."""
    return _write_tool(tmp_path / "definitely-signtool.cmd", ["hello from some other tool"])


# ── mode: обязателен, без default ───────────────────────────────────────────
def test_parse_mode_valid() -> None:
    assert sg.parse_mode("signed") == "signed"
    assert sg.parse_mode("internal") == "internal"


@pytest.mark.parametrize("bad", [None, "", "release", "prod", "SIGNED", "sign"])
def test_parse_mode_missing_or_unknown_fails(bad) -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.parse_mode(bad)
    assert "MODE" in str(exc.value)


# ── selector: ровно один (PFX xor thumbprint) ───────────────────────────────
def test_selector_pfx_only_ok() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass="p", thumbprint=None)
    assert sel["kind"] == "pfx"


def test_selector_thumbprint_only_ok() -> None:
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=SELECTOR_THUMB)
    assert sel["kind"] == "thumbprint"


def test_selector_both_rejected() -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.resolve_selector(pfx="c.pfx", pfx_pass=None, thumbprint="ABCD")
    assert "SELECTOR" in str(exc.value)


def test_selector_neither_rejected() -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=None)
    assert "SELECTOR" in str(exc.value)


# ── require_signing by mode ─────────────────────────────────────────────────
def test_require_signing_by_mode() -> None:
    assert sg.require_signing("signed") is True
    assert sg.require_signing("internal") is False


# ── preflight (fail-closed in signed mode; expects a signer THUMBPRINT) ──────
def test_preflight_internal_ok_without_anything() -> None:
    sg.preflight("internal", selector=None, signtool=None, expected_thumbprint=None,
                 timestamp_url="")  # internal нужен пустой контракт


def test_preflight_signed_fails_without_selector() -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=None, signtool="signtool.exe",
                     expected_thumbprint=THUMB, timestamp_url=TS)
    assert "SELECTOR" in str(exc.value)


def test_preflight_signed_fails_without_signtool(tmp_path: Path) -> None:
    sel = sg.resolve_selector(pfx=str(_pfx(tmp_path)), pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=None, expected_thumbprint=THUMB,
                     timestamp_url=TS)
    assert "SIGNTOOL" in str(exc.value)


def test_preflight_signed_fails_without_expected_thumbprint(tmp_path: Path) -> None:
    sel = sg.resolve_selector(pfx=str(_pfx(tmp_path)), pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool="signtool.exe",
                     expected_thumbprint="", timestamp_url=TS)
    assert "SIGNER" in str(exc.value)


def _pfx(tmp_path: Path) -> Path:
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"PFX")
    return pfx


def test_preflight_signed_ok_when_complete(tmp_path: Path) -> None:
    sel = sg.resolve_selector(pfx=str(_pfx(tmp_path)), pfx_pass="p", thumbprint=None)
    sg.preflight("signed", selector=sel, signtool="signtool.exe",
                 expected_thumbprint=THUMB, timestamp_url=TS, probe=lambda s: None)


# ── H6-6: полнота preflight (всё проверяется ДО compose) ────────────────────
def _real_exe() -> str:
    import sys as _sys
    return _sys.executable


def test_preflight_rejects_missing_pfx(tmp_path: Path, fake_signtool: str) -> None:
    sel = sg.resolve_selector(pfx=str(tmp_path / "nope.pfx"), pfx_pass="p", thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=fake_signtool,
                     expected_thumbprint=THUMB, timestamp_url=TS)
    assert "SELECTOR" in str(exc.value)


def test_preflight_rejects_a_directory_as_pfx(tmp_path: Path, fake_signtool: str) -> None:
    sel = sg.resolve_selector(pfx=str(tmp_path), pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError):
        sg.preflight("signed", selector=sel, signtool=fake_signtool,
                     expected_thumbprint=THUMB, timestamp_url=TS)


def test_preflight_rejects_a_non_executable_signtool(tmp_path: Path) -> None:
    fake = tmp_path / "signtool.exe"
    fake.write_bytes(b"not a real PE image")
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=SELECTOR_THUMB)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=str(fake),
                     expected_thumbprint=THUMB, timestamp_url=TS)
    assert "SIGNTOOL" in str(exc.value)


@pytest.mark.parametrize("bad", ["", "not-a-url", "ftp://ts.example", "timestamp.digicert.com"])
def test_preflight_rejects_invalid_timestamp_url(bad: str, fake_signtool: str) -> None:
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=SELECTOR_THUMB)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=fake_signtool,
                     expected_thumbprint=THUMB, timestamp_url=bad)
    assert "TR_URL" in str(exc.value)


@pytest.mark.parametrize("bad", ["ZZZZ", THUMB[:-1], THUMB + "AB", "not hex at all!!"])
def test_preflight_rejects_malformed_expected_thumbprint(bad: str,
                                                         fake_signtool: str) -> None:
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=SELECTOR_THUMB)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=fake_signtool,
                     expected_thumbprint=bad, timestamp_url=TS)
    assert "SIGNER" in str(exc.value)


def test_preflight_accepts_a_complete_contract(tmp_path: Path, fake_signtool: str) -> None:
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"PFX")
    sel = sg.resolve_selector(pfx=str(pfx), pfx_pass="p", thumbprint=None)
    sg.preflight("signed", selector=sel, signtool=fake_signtool,
                 expected_thumbprint=THUMB, timestamp_url=TS)  # не поднимает


# ── H7-6: проба проверяет ЛИЧНОСТЬ инструмента, а не факт запуска ───────────
def test_probe_accepts_a_tool_that_identifies_as_signtool(fake_signtool: str) -> None:
    sg.probe_signtool(fake_signtool)  # не поднимает


def test_probe_rejects_an_executable_that_is_not_signtool(not_signtool: str) -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.probe_signtool(not_signtool)
    assert "SIGNTOOL_IDENTITY" in str(exc.value)


def test_probe_rejects_cmd_exe() -> None:
    import os
    import sys as _sys
    if _sys.platform != "win32":
        pytest.skip("windows only")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.probe_signtool(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                       "System32", "cmd.exe"), args=["/c", "ver"])
    assert "SIGNTOOL_IDENTITY" in str(exc.value)


def test_probe_rejects_the_python_interpreter() -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.probe_signtool(_real_exe(), args=["-c", "print('hello')"])
    assert "SIGNTOOL_IDENTITY" in str(exc.value)


@pytest.mark.parametrize("bad", ["ABCD1234", "", "zz" * 20, SELECTOR_THUMB[:-1],
                                 SELECTOR_THUMB + "AB"])
def test_selector_thumbprint_must_be_40_hex(bad: str) -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=bad)
    assert "SELECTOR" in str(exc.value)


def test_probe_signtool_is_bounded(tmp_path: Path) -> None:
    # зависший signtool не должен вешать сборку — проба ограничена по времени
    slow = [_real_exe(), "-c", "import time; time.sleep(30)"]
    with pytest.raises(sg.SigningGateError) as exc:
        sg.probe_signtool(slow[0], args=slow[1:], timeout=0.5)
    assert "SIGNTOOL" in str(exc.value)


# ── sign command: SHA256 digest + RFC3161 SHA256 timestamp ──────────────────
def test_sign_command_uses_sha256_and_rfc3161_timestamp(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"
    f.write_bytes(b"x")
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass="secret", thumbprint=None)
    cmd = sg.build_sign_command(f, selector=sel, timestamp_url=TS, signtool="st.exe")
    assert cmd[:2] == ["st.exe", "sign"]
    assert "/fd" in cmd and cmd[cmd.index("/fd") + 1] == "SHA256"
    assert "/tr" in cmd and cmd[cmd.index("/tr") + 1] == TS
    assert "/td" in cmd and cmd[cmd.index("/td") + 1] == "SHA256"
    assert "/f" in cmd and cmd[cmd.index("/f") + 1] == "c.pfx"
    assert "/p" in cmd and cmd[cmd.index("/p") + 1] == "secret"
    assert cmd[-1] == str(f)


def test_sign_command_thumbprint_selector(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint=SELECTOR_THUMB)
    cmd = sg.build_sign_command(f, selector=sel, timestamp_url=TS, signtool="st.exe")
    assert "/sha1" in cmd and cmd[cmd.index('/sha1') + 1] == SELECTOR_THUMB
    assert "/f" not in cmd


# ── structured Authenticode inspection (no free-substring parsing) ──────────
def _report(status="Valid", thumbprint=THUMB, timestamped=True) -> dict:
    return {"status": status, "thumbprint": thumbprint, "timestamped": timestamped}


def test_inspect_signature_parses_structured_json(tmp_path: Path) -> None:
    import json
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    out = json.dumps({"Status": "Valid", "Thumbprint": "a1b2c3", "Timestamped": True})
    report = sg.inspect_signature(f, runner=lambda cmd: (0, out))
    assert report["status"] == "Valid"
    assert report["thumbprint"] == "A1B2C3"       # normalized upper
    assert report["timestamped"] is True


def test_inspect_signature_nonzero_raises(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    with pytest.raises(sg.SigningGateError):
        sg.inspect_signature(f, runner=lambda cmd: (1, ""))


def test_verify_signed_ok(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    sg.verify_signed(f, expected_thumbprint=THUMB, inspector=lambda p: _report())


def test_verify_signed_rejects_invalid_status(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.verify_signed(f, expected_thumbprint=THUMB,
                         inspector=lambda p: _report(status="HashMismatch"))
    assert "SIGN_VERIFY_FAILED" in str(exc.value)


def test_verify_signed_rejects_wrong_thumbprint(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.verify_signed(f, expected_thumbprint=THUMB,
                         inspector=lambda p: _report(thumbprint="DEADBEEF"))
    assert "WRONG_SIGNER" in str(exc.value)


def test_verify_signed_rejects_not_timestamped(tmp_path: Path) -> None:
    # F4#9: "The signature is not timestamped" must FAIL
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.verify_signed(f, expected_thumbprint=THUMB,
                         inspector=lambda p: _report(timestamped=False))
    assert "NO_TIMESTAMP" in str(exc.value)


def test_verify_signed_thumbprint_case_insensitive(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    sg.verify_signed(f, expected_thumbprint=THUMB.lower(),
                     inspector=lambda p: _report(thumbprint=THUMB.upper()))


# ── internal marker: written in place (naming happens at ISCC, no post-rename) ─
def test_write_internal_marker(tmp_path: Path) -> None:
    marker = sg.write_internal_marker(tmp_path, version="1.0.0-rc3")
    assert marker.name == "INTERNAL-UNSIGNED.txt"
    assert marker.is_file() and "DO-NOT-DISTRIBUTE" in marker.read_text(encoding="utf-8")


def test_mark_internal_unsigned_removed() -> None:
    # F4#7: post-build EXE rename is gone — naming is done by ISCC OutputBaseFilename
    assert not hasattr(sg, "mark_internal_unsigned")


# ── H3.1: ЕДИНЫЙ резолвер signtool (env → PATH → Windows Kits) ──────────────
def test_resolve_signtool_prefers_explicit_env(tmp_path: Path) -> None:
    own = tmp_path / "own-signtool.exe"
    own.write_bytes(b"MZ")
    assert sg.resolve_signtool({"KALI_SIGN_SIGNTOOL": str(own)},
                               which=lambda n: "C:/path/signtool.exe") == str(own)


def test_resolve_signtool_rejects_missing_explicit_path(tmp_path: Path) -> None:
    # H5: иначе .bat-guard «abort ДО compose» пропускает опечатку/переехавший SDK,
    # и падение случается уже после ~9 ГБ копирования, в момент подписи.
    with pytest.raises(sg.SigningGateError) as exc:
        sg.resolve_signtool({"KALI_SIGN_SIGNTOOL": str(tmp_path / "nope.exe")},
                            which=lambda n: "C:/path/signtool.exe")
    assert "KALI_SIGN_SIGNTOOL" in str(exc.value)


def test_resolve_signtool_uses_path_when_no_env() -> None:
    assert sg.resolve_signtool({}, which=lambda n: "C:/path/signtool.exe") == "C:/path/signtool.exe"


def test_resolve_signtool_falls_back_to_windows_kits(tmp_path: Path) -> None:
    # .bat знал про Windows Kits, а композер — нет: signed-билд проходил .bat и падал
    # на preflight композера. Теперь резолвер один.
    kit = tmp_path / "10.0.22621.0" / "x64"
    kit.mkdir(parents=True)
    (kit / "signtool.exe").write_bytes(b"MZ")
    found = sg.resolve_signtool({}, which=lambda n: None, kits_root=tmp_path)
    assert found == str(kit / "signtool.exe")


def test_resolve_signtool_none_when_nowhere(tmp_path: Path) -> None:
    assert sg.resolve_signtool({}, which=lambda n: None, kits_root=tmp_path) is None


# ── H3.3: docstring не должен обещать `signtool verify /pa` ─────────────────
def test_module_docstring_matches_structured_verify() -> None:
    assert "signtool verify /pa" not in (sg.__doc__ or "")
    assert "Get-AuthenticodeSignature" in (sg.__doc__ or "")


# ── G7: apostrophe-safe inspection (EncodedCommand + doubled PS quote) ───────
def test_inspect_command_apostrophe_path_is_safe(tmp_path: Path) -> None:
    import base64
    p = tmp_path / "O'Malley" / "app.exe"
    cmd = sg._inspect_command(p)
    assert cmd[-2] == "-EncodedCommand"
    decoded = base64.b64decode(cmd[-1]).decode("utf-16-le")
    assert "O''Malley" in decoded  # the apostrophe is doubled in the PS single-quoted literal
    assert "Get-AuthenticodeSignature -LiteralPath" in decoded


def test_powershell_inspector_reads_apostrophe_path_end_to_end(tmp_path: Path) -> None:
    # G7: the REAL PowerShell inspector must read a signature from a path containing an
    # apostrophe without a quoting failure (a real signed EXE is copied in).
    import shutil
    import sys as _sys
    if _sys.platform != "win32":
        pytest.skip("Authenticode inspection is Windows-only")
    d = tmp_path / "O'Malley Corp"; d.mkdir()
    exe = d / "app.exe"
    shutil.copy2(_sys.executable, exe)  # a real (often embedded-signed) Windows exe
    try:
        report = sg.powershell_inspector(exe)
    except sg.SigningGateError:
        pytest.skip("PowerShell inspection unavailable")
    assert set(report) == {"status", "thumbprint", "timestamped"}  # structured, no quoting break
