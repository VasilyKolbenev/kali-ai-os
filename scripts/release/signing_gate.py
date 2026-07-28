"""Fail-closed Windows code-signing policy (C4, OPUS-201).

A distributable release must carry a trusted Authenticode signature or the build
must fail. This module holds the *policy* (pure, unit-tested with an injected
command runner — no real signtool/cert needed):

* **mode** — every build declares ``signed`` or ``internal`` explicitly; a
  missing/unknown mode is refused (there is NO default release mode).
* **selector** — exactly one credential source: a PFX file OR a Windows
  certificate-store / HSM thumbprint (both or neither is refused).
* **signtool** — ONE resolver for the .bat and the composer: an explicit
  ``KALI_SIGN_SIGNTOOL``, then PATH, then the Windows Kits install.
* **preflight** — in ``signed`` mode, refuse up front unless a selector, a
  signtool and an expected signer identity are all present.
* **sign** — SHA256 file digest + an RFC3161 SHA256 timestamp.
* **verify** — a STRUCTURED PowerShell ``Get-AuthenticodeSignature`` report must
  show ``Status=Valid``, the EXACT expected signer thumbprint and a timestamp
  countersignature; anything else raises (no free-text substring matching).
* **internal marker** — an unsigned build is renamed to an explicit
  ``…-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE`` artifact with a marker file.

The actual EV/OV certificate stays an owner gate; its absence does not weaken any
check here — it only means a distributable ``signed`` build cannot be produced.
"""
from __future__ import annotations

import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from scripts.release import stage_policy

_THUMBPRINT_RE = re.compile(r"^[0-9A-Fa-f]{40}$")
# Tokens the real SignTool prints in its own usage banner; a binary that names none of
# them is not SignTool, however happily it launches.
_SIGNTOOL_CONTRACT = ("signtool", "sign", "timestamp", "verify")

MODES = ("signed", "internal")
INTERNAL_SUFFIX = "-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE"
INTERNAL_MARKER = "INTERNAL-UNSIGNED.txt"
_KITS_ROOT = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")

# runner(cmd) -> (returncode, combined_output)
Runner = Callable[[list[str]], "tuple[int, str]"]


class SigningGateError(Exception):
    """A signing-policy violation (fail-closed)."""


def parse_mode(arg: Any) -> str:
    """Return the explicit build mode; refuse a missing/unknown one (no default)."""
    if arg not in MODES:
        raise SigningGateError(
            f"MODE: build mode must be exactly 'signed' or 'internal', got {arg!r}"
        )
    return arg


def require_signing(mode: str) -> bool:
    """Signed builds must sign; internal builds must not be published."""
    return mode == "signed"


def resolve_selector(*, pfx: str | None, pfx_pass: str | None,
                     thumbprint: str | None) -> dict[str, Any]:
    """Exactly one credential: a PFX file OR a store/HSM thumbprint."""
    if bool(pfx) == bool(thumbprint):
        raise SigningGateError(
            "SELECTOR: exactly one of PFX or store/HSM thumbprint is required"
        )
    if pfx:
        return {"kind": "pfx", "pfx": pfx, "pass": pfx_pass}
    # H7-6: a store/HSM selector is a SHA-1 fingerprint — a malformed one must fail here,
    # not as an opaque signtool error after the stage has already been copied.
    if not _THUMBPRINT_RE.match(thumbprint or ""):
        raise SigningGateError(
            f"SELECTOR: KALI_SIGN_THUMBPRINT must be 40 hex chars, got {thumbprint!r}")
    return {"kind": "thumbprint", "thumbprint": thumbprint}


def _kit_candidates(kits_root: Path) -> list[Path]:
    """signtool.exe locations inside a Windows SDK install (newest layout first)."""
    versioned = sorted(kits_root.glob("*/x64/signtool.exe"), reverse=True)
    return [*versioned, kits_root / "x64" / "signtool.exe", kits_root / "x86" / "signtool.exe"]


def resolve_signtool(env: dict[str, str], *, which: Callable[[str], str | None] | None = None,
                     kits_root: Path | None = None) -> str | None:
    """The ONE signtool resolver (H3.1): explicit env, then PATH, then Windows Kits.

    The .bat and the composer used to resolve independently — only the .bat knew the
    Windows Kits fallback — so a machine without signtool on PATH passed the .bat's
    own check and then failed the composer's preflight (or, worse, the two could pick
    different binaries). Both now call this."""
    explicit = env.get("KALI_SIGN_SIGNTOOL")
    if explicit:
        if not Path(explicit).is_file():
            # A stale/mistyped path would otherwise satisfy the .bat's pre-compose
            # guard and only fail at signing time, after the multi-GB stage copy.
            raise SigningGateError(
                f"SIGNTOOL: KALI_SIGN_SIGNTOOL points at a missing file: {explicit}")
        return explicit
    lookup = which or shutil.which
    found = lookup("signtool") or lookup("signtool.exe")
    if found:
        return found
    for candidate in _kit_candidates(kits_root or _KITS_ROOT):
        if candidate.is_file():
            return str(candidate)
    return None


def assert_pfx_selector(selector: dict[str, Any]) -> None:
    """A PFX selector must point at an EXISTING regular file (H6-6)."""
    if selector.get("kind") != "pfx":
        return
    pfx = Path(str(selector.get("pfx") or ""))
    if not pfx.is_file():
        raise SigningGateError(f"SELECTOR: PFX is not an existing file: {pfx}")


def assert_expected_thumbprint(value: str) -> None:
    """An expected signer thumbprint is a SHA-1 fingerprint: exactly 40 hex chars."""
    if not _THUMBPRINT_RE.match(value or ""):
        raise SigningGateError(
            f"SIGNER: expected signer thumbprint must be 40 hex chars, got {value!r}")


def assert_timestamp_url(url: str) -> None:
    """The RFC3161 timestamp endpoint must be an absolute http(s) URL."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SigningGateError(f"TR_URL: invalid RFC3161 timestamp URL: {url!r}")


def _original_filename(path: str) -> str | None:
    """The PE VersionInfo OriginalFilename, read via PowerShell (apostrophe-safe)."""
    import subprocess
    quoted = path.replace("'", "''")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-Item -LiteralPath '{quoted}').VersionInfo.OriginalFilename"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    return (proc.stdout or "").strip() or None


def assert_signtool_identity(signtool: str, *,
                             identity_reader: Callable[[str], "str | None"] | None = None
                             ) -> None:
    """A minimal IDENTITY contract for the signing tool (H8-3).

    "It started and printed something" is trivially forged by a .cmd or a stub, and the
    thing this path hands a private key to must not be forgeable that cheaply. The
    contract: a physical .exe, a real PE image, and a VersionInfo OriginalFilename of
    SignTool.exe. A genuine SDK signtool is still only proven at the live gate."""
    path = Path(signtool)
    if stage_policy.is_reparse_point(path) or not path.is_file():
        raise SigningGateError(f"SIGNTOOL_IDENTITY: not a physical file: {signtool}")
    if path.suffix.lower() != ".exe":
        raise SigningGateError(
            f"SIGNTOOL_IDENTITY: refusing a script/wrapper, expected a .exe: {signtool}")
    with path.open("rb") as fh:
        if fh.read(2) != b"MZ":
            raise SigningGateError(f"SIGNTOOL_IDENTITY: not a PE image: {signtool}")
    identity = (identity_reader or _original_filename)(signtool)
    if (identity or "").strip().lower() != "signtool.exe":
        raise SigningGateError(
            f"SIGNTOOL_IDENTITY: OriginalFilename is {identity!r}, expected SignTool.exe")


def probe_signtool(signtool: str, *, args: list[str] | None = None,
                   timeout: float = 20.0,
                   identity_reader: Callable[[str], "str | None"] | None = None) -> None:
    """BOUNDED IDENTITY probe: the resolved binary must actually BE SignTool (H7-6).

    "It starts" is not a contract — cmd.exe starts, python starts, any executable
    starts. The probe requires the tool's own usage banner to name SignTool and its
    verbs, so a wrong or spoofed binary is refused before the multi-GB stage copy
    rather than at signing time. stdin is closed so an interactive binary cannot block
    and the timeout bounds a hung one."""
    import subprocess
    # H8-3: identity FIRST — a .cmd/.ps1 or a stub can forge any banner, so the banner
    # alone is not a contract. Physical .exe + PE image + OriginalFilename=SignTool.exe.
    assert_signtool_identity(signtool, identity_reader=identity_reader)
    try:
        proc = subprocess.run([signtool, *(args or [])], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except OSError as e:
        raise SigningGateError(f"SIGNTOOL: {signtool} is not executable: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise SigningGateError(
            f"SIGNTOOL: {signtool} did not respond within {timeout}s") from e
    banner = ((proc.stdout or "") + (proc.stderr or "")).lower()
    missing = [token for token in _SIGNTOOL_CONTRACT if token not in banner]
    if missing:
        raise SigningGateError(
            f"SIGNTOOL_IDENTITY: {signtool} does not identify as SignTool "
            f"(its output names none of {missing})")


def preflight(mode: str, *, selector: dict[str, Any] | None, signtool: str | None,
              expected_thumbprint: str | None, timestamp_url: str,
              probe: Callable[[str], None] | None = None) -> None:
    """Fail-closed pre-build check: an internal build needs nothing; a signed build
    refuses unless the WHOLE contract holds — selector present and usable, signtool
    present and executable, a well-formed signer thumbprint and a valid timestamp URL.
    Everything here runs BEFORE any stage mutation."""
    if not require_signing(mode):
        return
    if selector is None:
        raise SigningGateError("SELECTOR: signed build requires a signing selector")
    if not signtool:
        raise SigningGateError("SIGNTOOL: signed build requires signtool.exe")
    if not expected_thumbprint:
        raise SigningGateError("SIGNER: signed build requires an expected signer thumbprint")
    assert_pfx_selector(selector)
    assert_expected_thumbprint(expected_thumbprint)
    assert_timestamp_url(timestamp_url)
    (probe or probe_signtool)(signtool)


def build_sign_command(file: Path, *, selector: dict[str, Any], timestamp_url: str,
                       signtool: str) -> list[str]:
    """signtool sign with SHA256 digest + RFC3161 SHA256 timestamp + selector."""
    cmd = [signtool, "sign", "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256"]
    if selector["kind"] == "pfx":
        cmd += ["/f", selector["pfx"]]
        if selector.get("pass"):
            cmd += ["/p", selector["pass"]]
    else:
        cmd += ["/sha1", selector["thumbprint"]]
    cmd.append(str(file))
    return cmd


def _inspect_command(file: Path, *, powershell: str = "powershell") -> list[str]:
    """PowerShell Get-AuthenticodeSignature as STRUCTURED JSON (no substring parsing).

    The path is embedded in a single-quoted PS literal with apostrophes doubled
    (so ``C:\\O'Malley\\app.exe`` is safe), and the whole script is passed via
    ``-EncodedCommand`` (base64 UTF-16LE) so no shell/cmd quoting can mangle it."""
    import base64
    ps_path = str(file).replace("'", "''")  # escape for a PS single-quoted literal
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{ps_path}'; "
        "[pscustomobject]@{ Status = [string]$s.Status; "
        "Thumbprint = if ($s.SignerCertificate) { $s.SignerCertificate.Thumbprint } else { '' }; "
        "Timestamped = [bool]$s.TimeStamperCertificate } | ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def inspect_signature(file: Path, *, runner: Runner) -> dict[str, Any]:
    """Structured Authenticode report: {status, thumbprint (upper), timestamped}."""
    import json
    rc, out = runner(_inspect_command(file))
    if rc != 0:
        raise SigningGateError(f"SIGN_INSPECT_FAILED: rc={rc}: {out[:200]}")
    try:
        data = json.loads(out)
    except (ValueError, TypeError) as e:
        raise SigningGateError(f"SIGN_INSPECT_MALFORMED: {out[:120]!r}") from e
    return {
        "status": str(data.get("Status", "")),
        "thumbprint": str(data.get("Thumbprint") or "").upper(),
        "timestamped": bool(data.get("Timestamped")),
    }


Inspector = Callable[[Path], "dict[str, Any]"]


def verify_signed(file: Path, *, expected_thumbprint: str, inspector: Inspector) -> None:
    """Fail-closed structured verify: Status==Valid, EXACT signer thumbprint, timestamp."""
    report = inspector(file)
    if report.get("status") != "Valid":
        raise SigningGateError(f"SIGN_VERIFY_FAILED: Authenticode status={report.get('status')!r}")
    if report.get("thumbprint", "").upper() != expected_thumbprint.upper():
        raise SigningGateError(
            f"WRONG_SIGNER: thumbprint {report.get('thumbprint')!r} != expected")
    if not report.get("timestamped"):
        # The inspector proves a countersignature (TimeStamperCertificate) exists; the
        # sign path requests an RFC3161 /tr timestamp, but the inspector does not
        # structurally distinguish RFC3161 from a legacy Authenticode timestamp.
        raise SigningGateError("NO_TIMESTAMP: signature has no timestamp countersignature")


def powershell_inspector(file: Path) -> dict[str, Any]:
    """Production inspector — runs PowerShell Get-AuthenticodeSignature."""
    import subprocess

    def _runner(cmd: list[str]) -> tuple[int, str]:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout
    return inspect_signature(file, runner=_runner)


def write_internal_marker(directory: Path, *, version: str) -> Path:
    """Drop the INTERNAL-UNSIGNED marker (naming is done by ISCC OutputBaseFilename;
    there is no post-build EXE rename)."""
    marker = directory / INTERNAL_MARKER
    marker.write_text(
        f"INTERNAL-UNSIGNED build of KALI Premium {version}.\n"
        "DO-NOT-DISTRIBUTE: this artifact is UNSIGNED and is for local, "
        "trusted-alpha verification only. A public release requires a trusted "
        "Authenticode code-signing identity.\n",
        encoding="utf-8",
    )
    return marker
