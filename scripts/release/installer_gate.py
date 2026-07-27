"""Installer wiring policy (C7, OPUS-201).

The Windows installer build declares an explicit ``signed`` or ``internal`` mode
and this gate enforces the fail-closed rules the .bat/.iss delegate to it:

* an ``internal`` build is refused when the release is marked distributable
  (an unsigned artifact must never masquerade as a public one);
* ``release-status.json`` is the single source of the distributable flag
  (fail-closed on missing / non-bool);
* the .iss must pull [Files] only from ``premium_stage`` and must sign both the
  Setup and the uninstaller.

The .bat consumes the CLI: ``resolve-mode <mode> <release-status.json>`` prints
the validated mode (or exits non-zero); ``mark-internal <setup> <version>``
renames an unsigned Setup to the DO-NOT-DISTRIBUTE artifact.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from scripts.release import signing_gate

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_SOURCE_KEY_RE = re.compile(r"(?i)(?:^|;)\s*Source\s*:\s*")
_QUOTED_RE = re.compile(r'^"([^"]*)"')
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
# The .iss lives in scripts/, so its relative Sources resolve against that dir. The
# only legal file source is strictly BELOW ..\dist_premium\premium_stage\.
_ISS_BASE = ("<repo>", "scripts")
_STAGE_PREFIX = ("<repo>", "dist_premium", "premium_stage")


class InstallerGateError(Exception):
    """An installer wiring-policy violation (fail-closed)."""


def read_distributable(release_status_path: Path) -> bool:
    """The single source of publish permission; fail-closed on missing/non-bool."""
    if not release_status_path.is_file():
        raise InstallerGateError(f"STATUS_MISSING: {release_status_path}")
    try:
        data = json.loads(release_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InstallerGateError(f"STATUS_MALFORMED: {e}") from e
    value = data.get("distributable")
    if not isinstance(value, bool):
        raise InstallerGateError("STATUS_SCHEMA: 'distributable' must be a bool")
    return value


def resolve_build_mode(mode_arg: object, *, distributable: bool) -> str:
    """Validate the explicit build mode and refuse internal+distributable."""
    mode = signing_gate.parse_mode(mode_arg)
    if mode == "internal" and distributable is True:
        raise InstallerGateError(
            "INTERNAL_DISTRIBUTABLE: an internal (unsigned) build is forbidden "
            "when release-status.distributable is true"
        )
    return mode


def _files_section(iss_text: str) -> list[str]:
    """The raw lines of the ``[Files]`` section (fail-closed if it is absent)."""
    lines: list[str] = []
    inside = False
    seen = False
    for raw in iss_text.splitlines():
        section = _SECTION_RE.match(raw)
        if section:
            inside = section.group("name").strip().lower() == "files"
            seen = seen or inside
            continue
        if inside:
            lines.append(raw)
    if not seen:
        raise InstallerGateError("ISS_NO_FILES_SECTION: the .iss declares no [Files]")
    return lines


def _logical_lines(lines: list[str]) -> list[str]:
    """Join Inno's backslash line continuations into single logical entries."""
    joined: list[str] = []
    buffer = ""
    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1]
            continue
        joined.append(buffer + stripped)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def _iss_sources(iss_text: str) -> list[str]:
    """Every ``Source:`` value declared in [Files], as written.

    A ``Source:`` whose value is not a double-quoted literal is refused rather than
    skipped: an unparsed entry used to slip past the gate entirely."""
    sources: list[str] = []
    for line in _logical_lines(_files_section(iss_text)):
        if line.lstrip().startswith(";"):
            continue  # a comment line
        if line.lstrip().lower().startswith("#include"):
            # ISPP pulls in entries this gate cannot see — fail closed rather than
            # certify a [Files] section whose real content lives in another file.
            raise InstallerGateError(f"ISS_UNRESOLVED_INCLUDE: {line.strip()!r}")
        for match in _SOURCE_KEY_RE.finditer(line):
            quoted = _QUOTED_RE.match(line[match.end():])
            if not quoted:
                raise InstallerGateError(f"ISS_SOURCE_UNQUOTED: {line.strip()!r}")
            sources.append(quoted.group(1))
    return sources


def _normalize_source(raw: str) -> tuple[str, ...]:
    """Normalize a relative Source into path parts rooted at the repo (``..`` resolved)."""
    if not raw.strip():
        raise InstallerGateError("ISS_SOURCE_EMPTY: an empty Source is not a file source")
    path = raw.replace("/", "\\")
    if _DRIVE_RE.match(path) or path.startswith("\\"):
        raise InstallerGateError(f"ISS_SOURCE_ABSOLUTE: {raw}")
    if "{" in path:  # an Inno constant ({app}, {tmp}, ...) is not a stage-relative file
        raise InstallerGateError(f"ISS_SOURCE_CONSTANT: {raw}")
    parts = list(_ISS_BASE)
    for segment in path.split("\\"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if len(parts) <= 1:  # would escape above the repo root
                raise InstallerGateError(f"ISS_SOURCE_OUTSIDE_STAGE: {raw}")
            parts.pop()
            continue
        parts.append(segment)
    return tuple(parts)


def assert_iss_stage_only(iss_text: str) -> None:
    """[Files] must declare at least one Source and each must resolve strictly under
    ``..\\dist_premium\\premium_stage\\``.

    This is a real path check, not a substring one: ``premium_stage_evil`` and
    ``premium_stage\\..\\..\\scripts`` are both outside the sealed stage."""
    sources = _iss_sources(iss_text)
    if not sources:
        raise InstallerGateError("ISS_NO_SOURCE: [Files] declares no Source")
    depth = len(_STAGE_PREFIX)
    lowered_prefix = tuple(p.lower() for p in _STAGE_PREFIX)
    for raw in sources:
        parts = _normalize_source(raw)
        contained = (len(parts) > depth
                     and tuple(p.lower() for p in parts[:depth]) == lowered_prefix)
        if not contained:
            raise InstallerGateError(f"ISS_SOURCE_OUTSIDE_STAGE: {raw}")


def assert_iss_signs_setup_and_uninstaller(iss_text: str) -> None:
    """The .iss must sign both the Setup and the generated uninstaller."""
    if "SignedUninstaller=yes" not in iss_text:
        raise InstallerGateError("NO_UNINSTALLER_SIGN: SignedUninstaller=yes missing")
    if "SignTool=" not in iss_text:
        raise InstallerGateError("NO_SETUP_SIGN: SignTool= directive missing")


def assert_iss_internal_naming(iss_text: str) -> None:
    """An internal build must name Setup AND every slice INTERNAL at ISCC time
    (a conditional OutputBaseFilename), never by a post-build EXE rename."""
    if "INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE" not in iss_text:
        raise InstallerGateError(
            "NO_INTERNAL_NAMING: conditional INTERNAL OutputBaseFilename missing")
    if "#ifdef Internal" not in iss_text:
        raise InstallerGateError("NO_INTERNAL_GUARD: #ifdef Internal guard missing")


def verify_iss(iss_text: str) -> None:
    """Full .iss wiring gate (run by the .bat before compose): stage-only Sources,
    Setup + uninstaller signing, and INTERNAL-at-compile naming."""
    assert_iss_stage_only(iss_text)
    assert_iss_signs_setup_and_uninstaller(iss_text)
    assert_iss_internal_naming(iss_text)


def _die(msg: str) -> None:
    print(f"installer_gate: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    """CLI consumed by build_installer_premium.bat."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _die("usage: installer_gate <resolve-mode|write-marker> ...")
    try:
        if args[0] == "resolve-mode":
            mode_arg, status = args[1], Path(args[2])
            mode = resolve_build_mode(mode_arg, distributable=read_distributable(status))
            print(mode)
            return 0
        if args[0] == "write-marker":
            marker = signing_gate.write_internal_marker(Path(args[1]), version=args[2])
            print(marker)
            return 0
        if args[0] == "verify-setup":
            signing_gate.verify_signed(Path(args[1]), expected_thumbprint=args[2],
                                       inspector=signing_gate.powershell_inspector)
            print("verified")
            return 0
        if args[0] == "verify-iss":
            verify_iss(Path(args[1]).read_text(encoding="utf-8"))
            print("ok")
            return 0
        if args[0] == "resolve-signtool":
            # The .bat consumes this so it cannot keep its own (narrower) path list.
            signtool = signing_gate.resolve_signtool(dict(os.environ))
            if not signtool:
                _die("SIGNTOOL: signtool.exe not found (PATH or Windows Kits)")
            print(signtool)
            return 0
    except (InstallerGateError, signing_gate.SigningGateError) as e:
        _die(str(e))
    _die(f"unknown command: {args[0]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
