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
TS = "http://timestamp.digicert.com"


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
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint="ABCD1234")
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
    sg.preflight("internal", selector=None, signtool=None, expected_thumbprint=None)  # ok


def test_preflight_signed_fails_without_selector() -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=None, signtool="signtool.exe",
                     expected_thumbprint=THUMB)
    assert "SELECTOR" in str(exc.value)


def test_preflight_signed_fails_without_signtool() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=None, expected_thumbprint=THUMB)
    assert "SIGNTOOL" in str(exc.value)


def test_preflight_signed_fails_without_expected_thumbprint() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool="signtool.exe", expected_thumbprint="")
    assert "SIGNER" in str(exc.value)


def test_preflight_signed_ok_when_complete() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass="p", thumbprint=None)
    sg.preflight("signed", selector=sel, signtool="signtool.exe", expected_thumbprint=THUMB)


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
    sel = sg.resolve_selector(pfx=None, pfx_pass=None, thumbprint="ABCD1234")
    cmd = sg.build_sign_command(f, selector=sel, timestamp_url=TS, signtool="st.exe")
    assert "/sha1" in cmd and cmd[cmd.index("/sha1") + 1] == "ABCD1234"
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
