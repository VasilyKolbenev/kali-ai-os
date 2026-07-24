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
import re
import sys
from pathlib import Path

from scripts.release import signing_gate

_SOURCE_RE = re.compile(r'^\s*Source:\s*"([^"]+)"', re.MULTILINE)


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


def assert_iss_stage_only(iss_text: str) -> None:
    """Every [Files] Source must come from premium_stage (no external inputs)."""
    outside = [s for s in _SOURCE_RE.findall(iss_text) if "premium_stage" not in s]
    if outside:
        raise InstallerGateError(f"ISS_SOURCE_OUTSIDE_STAGE: {outside}")


def assert_iss_signs_setup_and_uninstaller(iss_text: str) -> None:
    """The .iss must sign both the Setup and the generated uninstaller."""
    if "SignedUninstaller=yes" not in iss_text:
        raise InstallerGateError("NO_UNINSTALLER_SIGN: SignedUninstaller=yes missing")
    if "SignTool=" not in iss_text:
        raise InstallerGateError("NO_SETUP_SIGN: SignTool= directive missing")


def _die(msg: str) -> None:
    print(f"installer_gate: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    """CLI consumed by build_installer_premium.bat."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _die("usage: installer_gate <resolve-mode|mark-internal> ...")
    try:
        if args[0] == "resolve-mode":
            mode_arg, status = args[1], Path(args[2])
            mode = resolve_build_mode(mode_arg, distributable=read_distributable(status))
            print(mode)
            return 0
        if args[0] == "mark-internal":
            renamed, _marker = signing_gate.mark_internal_unsigned(
                Path(args[1]), version=args[2]
            )
            print(renamed)
            return 0
    except (InstallerGateError, signing_gate.SigningGateError) as e:
        _die(str(e))
    _die(f"unknown command: {args[0]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
