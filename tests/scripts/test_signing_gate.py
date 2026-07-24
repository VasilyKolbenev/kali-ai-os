"""TDD (red-first) для scripts/release/signing_gate.py — C4 OPUS-201.

Fail-closed signing policy. Реальный signtool/cert не запускаются: runner
инъектируется. Матрица mode/selector/signer/timestamp; reason-token в исключении.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release import signing_gate as sg

SIGNER = "KALI Labs LLC"
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


# ── preflight (fail-closed in signed mode) ──────────────────────────────────
def test_preflight_internal_ok_without_anything() -> None:
    sg.preflight("internal", selector=None, signtool=None, expected_signer=None)  # ok


def test_preflight_signed_fails_without_selector() -> None:
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=None, signtool="signtool.exe",
                     expected_signer=SIGNER)
    assert "SELECTOR" in str(exc.value)


def test_preflight_signed_fails_without_signtool() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool=None, expected_signer=SIGNER)
    assert "SIGNTOOL" in str(exc.value)


def test_preflight_signed_fails_without_expected_signer() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass=None, thumbprint=None)
    with pytest.raises(sg.SigningGateError) as exc:
        sg.preflight("signed", selector=sel, signtool="signtool.exe", expected_signer="")
    assert "SIGNER" in str(exc.value)


def test_preflight_signed_ok_when_complete() -> None:
    sel = sg.resolve_selector(pfx="c.pfx", pfx_pass="p", thumbprint=None)
    sg.preflight("signed", selector=sel, signtool="signtool.exe", expected_signer=SIGNER)


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


# ── verify_signed: Authenticode chain + expected signer + timestamp ─────────
_GOOD_OUT = (
    "Verifying: app.exe\n"
    "Signing Certificate Chain:\n"
    f"    Issued to: {SIGNER}\n"
    "The signature is timestamped: Fri Jul 24 10:00:00 2026\n"
    "Successfully verified: app.exe\n"
)


def test_verify_signed_ok_when_chain_signer_timestamp_present(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    sg.verify_signed(f, signtool="st.exe", expected_signer=SIGNER,
                     runner=lambda cmd: (0, _GOOD_OUT))  # не поднимает


def test_verify_signed_raises_on_nonzero(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.verify_signed(f, signtool="st.exe", expected_signer=SIGNER,
                         runner=lambda cmd: (1, "No signature found."))
    assert "SIGN_VERIFY_FAILED" in str(exc.value)


def test_verify_signed_raises_on_wrong_signer(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    wrong = _GOOD_OUT.replace(SIGNER, "Somebody Else Inc")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.verify_signed(f, signtool="st.exe", expected_signer=SIGNER,
                         runner=lambda cmd: (0, wrong))
    assert "WRONG_SIGNER" in str(exc.value)


def test_verify_signed_raises_on_missing_timestamp(tmp_path: Path) -> None:
    f = tmp_path / "app.exe"; f.write_bytes(b"x")
    no_ts = _GOOD_OUT.replace("The signature is timestamped: Fri Jul 24 10:00:00 2026\n", "")
    with pytest.raises(sg.SigningGateError) as exc:
        sg.verify_signed(f, signtool="st.exe", expected_signer=SIGNER,
                         runner=lambda cmd: (0, no_ts))
    assert "NO_TIMESTAMP" in str(exc.value)


# ── internal marker ─────────────────────────────────────────────────────────
def test_mark_internal_unsigned_renames_and_writes_marker(tmp_path: Path) -> None:
    setup = tmp_path / "KALI-Premium-Setup-1.0.0-rc3.exe"
    setup.write_bytes(b"SETUP")
    renamed, marker = sg.mark_internal_unsigned(setup, version="1.0.0-rc3")
    assert renamed.name == "KALI-Premium-Setup-1.0.0-rc3-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE.exe"
    assert renamed.is_file() and renamed.read_bytes() == b"SETUP"
    assert not setup.exists()  # original distributable name gone
    assert marker.name == "INTERNAL-UNSIGNED.txt"
    assert marker.is_file() and "DO-NOT-DISTRIBUTE" in marker.read_text(encoding="utf-8")
