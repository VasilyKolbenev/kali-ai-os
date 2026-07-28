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
import shutil
import sys
from pathlib import Path

from scripts.release import signing_gate, stage_policy

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_SOURCE_KEY_RE = re.compile(r"(?i)(?:^|;)\s*Source\s*:\s*")
_QUOTED_RE = re.compile(r'^"([^"]*)"')
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
# The .iss lives in scripts/, so its relative Sources resolve against that dir. The
# only legal file source is strictly BELOW ..\dist_premium\premium_stage\.
_ISS_BASE = ("<repo>", "scripts")
_STAGE_PREFIX = ("<repo>", "dist_premium", "premium_stage")
_DIRECTIVE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")
_UNINS_EXE_RE = re.compile(r"^unins\d{3}\.exe$")
SIGNED_DEFINES = frozenset({"SignSetup"})
INTERNAL_DEFINES = frozenset({"Internal"})
INTERNAL_NAME = "INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE"
INSTALLER_MANIFEST = "INSTALLER_ARTIFACTS.json"
_SLICE_RE = re.compile(r"^(?P<base>.+)-(?P<n>\d+)\.bin$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _files_section(active: list[str]) -> list[str]:
    """The ACTIVE lines of the ``[Files]`` section (fail-closed if it is absent)."""
    lines: list[str] = []
    inside = False
    seen = False
    for raw in active:
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


def _iss_sources(active: list[str]) -> list[str]:
    """Every ``Source:`` value declared in the ACTIVE [Files], as written.

    A ``Source:`` whose value is not a double-quoted literal is refused rather than
    skipped: an unparsed entry used to slip past the gate entirely."""
    sources: list[str] = []
    for line in _logical_lines(_files_section(active)):
        if line.lstrip().startswith(";"):
            continue  # a comment line
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
    depth = len(_STAGE_PREFIX)
    lowered_prefix = tuple(p.lower() for p in _STAGE_PREFIX)
    for defines in (SIGNED_DEFINES, INTERNAL_DEFINES):  # both real build views
        sources = _iss_sources(active_lines(iss_text, defines))
        if not sources:
            raise InstallerGateError(
                f"ISS_NO_SOURCE: [Files] declares no Source with {sorted(defines)} defined")
        for raw in sources:
            parts = _normalize_source(raw)
            contained = (len(parts) > depth
                         and tuple(p.lower() for p in parts[:depth]) == lowered_prefix)
            if not contained:
                raise InstallerGateError(f"ISS_SOURCE_OUTSIDE_STAGE: {raw}")


def active_directives(iss_text: str, defines: frozenset[str]) -> list[tuple[str, str]]:
    """Every ACTIVE ``key=value`` directive as ``(key_lower, value)`` under ``defines``.

    Comment lines are inactive and whitespace/case are normalized; which lines are
    active at all is decided by the conditional evaluator in :func:`active_lines`."""
    return _parse_directives(active_lines(iss_text, defines))


def _parse_directives(lines: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in lines:
        if line.startswith(("#", "[")):
            continue
        match = _DIRECTIVE_RE.match(line)
        if match:
            out.append((match.group("key").lower(), match.group("value").strip()))
    return out


def active_lines(iss_text: str, defines: frozenset[str]) -> list[str]:
    """Evaluate ISPP conditionals for a GIVEN define set and return the surviving lines.

    H7-1 — a real evaluator, not a guard list: ``#ifdef`` and ``#ifndef`` are opposites,
    ``#else`` inverts its own frame, nesting is honoured, and an inactive outer frame
    keeps everything inside it inactive. Anything it cannot evaluate — an unknown
    directive, a stray ``#else``/``#endif`` or an unbalanced file — fails closed rather
    than being skipped, because a skipped conditional silently changes what ships."""
    frames: list[tuple[bool, bool]] = []  # (this branch active, any branch taken yet)
    live = set(defines)
    out: list[str] = []
    for raw in iss_text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "//")):
            continue
        enclosing_active = all(active for active, _ in frames)
        if line.startswith("#"):
            word = line.split(None, 1)[0].lower()
            rest = line.split(None, 1)[1].strip() if " " in line else ""
            if word in ("#ifdef", "#ifndef"):
                if not rest:
                    raise InstallerGateError(f"ISS_BAD_CONDITIONAL: {line!r}")
                # only this frame's own condition is stored; enclosing frames are ANDed
                # in per line, so an inactive outer frame keeps everything inside it off
                taken = (rest in live) if word == "#ifdef" else (rest not in live)
                frames.append((taken, taken))
                continue
            if word == "#else":
                if not frames:
                    raise InstallerGateError(f"ISS_BAD_CONDITIONAL: stray {line!r}")
                _, taken = frames.pop()
                frames.append((not taken, True))
                continue
            if word == "#endif":
                if not frames:
                    raise InstallerGateError(f"ISS_BAD_CONDITIONAL: stray {line!r}")
                frames.pop()
                continue
            if word == "#define":
                if enclosing_active and rest:
                    live.add(rest.split(None, 1)[0].strip())
                continue
            if word == "#undef":
                if enclosing_active and rest:
                    live.discard(rest.split(None, 1)[0].strip())
                continue
            if word == "#include":
                raise InstallerGateError(f"ISS_UNRESOLVED_INCLUDE: {line!r}")
            raise InstallerGateError(f"ISS_UNKNOWN_DIRECTIVE: {line!r}")
        if enclosing_active:
            out.append(line)
    if frames:
        raise InstallerGateError("ISS_BAD_CONDITIONAL: unbalanced #ifdef/#endif")
    return out


def _has_directive(directives: list[tuple[str, str]], key: str, *,
                   value: str | None = None, contains: str | None = None) -> bool:
    for found_key, found_value in directives:
        if found_key != key:
            continue
        if value is not None and found_value.lower() != value.lower():
            continue
        if contains is not None and contains not in found_value:
            continue
        return True
    return False


def assert_iss_signs_setup_and_uninstaller(iss_text: str) -> None:
    """Signing must be ACTIVE in the signed view and INACTIVE in the internal one.

    Active in the internal view too would make an unsigned build demand a SignTool;
    inactive in the signed view (e.g. written under ``#ifndef SignSetup``) would ship an
    unsigned Setup while the raw text still 'mentions' the directives."""
    signed = active_directives(iss_text, SIGNED_DEFINES)
    internal = active_directives(iss_text, INTERNAL_DEFINES)
    if not _has_directive(signed, "signtool"):
        raise InstallerGateError(
            f"NO_SETUP_SIGN: SignTool= is not active with {sorted(SIGNED_DEFINES)} defined")
    if not _has_directive(signed, "signeduninstaller", value="yes"):
        raise InstallerGateError(
            f"NO_UNINSTALLER_SIGN: SignedUninstaller=yes is not active with "
            f"{sorted(SIGNED_DEFINES)} defined")
    if _has_directive(internal, "signtool") or _has_directive(internal, "signeduninstaller"):
        raise InstallerGateError(
            "SIGN_LEAKS_INTO_INTERNAL: signing directives are active in an internal build")


def assert_iss_internal_naming(iss_text: str) -> None:
    """The INTERNAL OutputBaseFilename must be active ONLY in the internal view."""
    internal = active_directives(iss_text, INTERNAL_DEFINES)
    signed = active_directives(iss_text, SIGNED_DEFINES)
    if not _has_directive(internal, "outputbasefilename", contains=INTERNAL_NAME):
        raise InstallerGateError(
            f"NO_INTERNAL_NAMING: no active OutputBaseFilename containing {INTERNAL_NAME} "
            f"with {sorted(INTERNAL_DEFINES)} defined")
    if _has_directive(signed, "outputbasefilename", contains=INTERNAL_NAME):
        raise InstallerGateError(
            "INTERNAL_NAME_LEAKS_INTO_SIGNED: a signed build would be named INTERNAL")


def verify_installed_uninstaller(root: Path, *, expected_thumbprint: str,
                                 inspector: signing_gate.Inspector) -> int:
    """Signed live acceptance (H6-4): every installed uninsNNN.exe must carry a VALID
    signature by the EXACT expected signer, with a timestamp countersignature."""
    uninstallers = sorted(p for p in root.iterdir()
                          if p.is_file() and _UNINS_EXE_RE.match(p.name))
    if not uninstallers:
        raise InstallerGateError(f"UNINSTALLER_MISSING: no uninsNNN.exe in {root}")
    for exe in uninstallers:
        signing_gate.verify_signed(exe, expected_thumbprint=expected_thumbprint,
                                   inspector=inspector)
    return len(uninstallers)


def verify_iss(iss_text: str) -> None:
    """Full .iss wiring gate (run by the .bat before compose): stage-only Sources,
    Setup + uninstaller signing, and INTERNAL-at-compile naming."""
    assert_iss_stage_only(iss_text)
    assert_iss_signs_setup_and_uninstaller(iss_text)
    assert_iss_internal_naming(iss_text)


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def collect_installer_artifacts(out_dir: Path, setup_name: str) -> dict:
    """The EXACT artifact set: the Setup plus its CONTIGUOUS -1..-N slices (H6-5).

    ISCC used to write into a directory that could still hold slices from a previous,
    larger build; publish then globbed and shipped a stale ``-3.bin``. Here the set is
    derived once, and anything else in the directory is an error rather than a guess."""
    setup = out_dir / setup_name
    if not setup.is_file():
        raise InstallerGateError(f"SETUP_MISSING: {setup}")
    base = setup_name[:-4] if setup_name.lower().endswith(".exe") else setup_name
    numbered: dict[int, Path] = {}
    for item in out_dir.iterdir():
        match = _SLICE_RE.match(item.name)
        if match and match.group("base") == base:
            numbered[int(match.group("n"))] = item
    ordered: list[Path] = []
    index = 1
    while index in numbered:
        ordered.append(numbered[index])
        index += 1
    orphans = sorted(p.name for n, p in numbered.items() if n >= index)
    if orphans:
        raise InstallerGateError(f"NONCONTIGUOUS_SLICES: {orphans}")
    files = [setup, *ordered]
    known = {p.name for p in files} | {INSTALLER_MANIFEST, "release-manifest.json",
                                       signing_gate.INTERNAL_MARKER}
    stray = sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.name not in known)
    if stray:
        raise InstallerGateError(f"STRAY_OUTPUT: {stray}")
    return {"setup": setup_name,
            "files": [{"name": f.name, "sha256": _sha256_file(f), "size": f.stat().st_size}
                      for f in files]}


def write_installer_manifest(out_dir: Path, setup_name: str) -> Path:
    """Seal the exact artifact set produced by this ISCC run."""
    manifest = collect_installer_artifacts(out_dir, setup_name)
    path = out_dir / INSTALLER_MANIFEST
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _safe_artifact_path(out_dir: Path, name: object) -> Path:
    """A manifest name must be a SAFE BASENAME resolving to a contained regular file.

    H7-2 — the manifest is a list of names that later get read, hashed and uploaded, so
    a traversal (``..\\..\\secret``), an absolute path, a separator or a reparse point
    must be refused before anything touches the filesystem."""
    if not isinstance(name, str) or not name or not _SAFE_NAME_RE.match(name):
        raise InstallerGateError(f"ARTIFACT_NAME_UNSAFE: {name!r}")
    if name in (".", "..") or Path(name).name != name:
        raise InstallerGateError(f"ARTIFACT_NAME_UNSAFE: {name!r}")
    item = out_dir / name
    if stage_policy.is_reparse_point(item):  # checked BEFORE resolve(), which follows it
        raise InstallerGateError(f"ARTIFACT_REPARSE: {item}")
    resolved = item.resolve()
    if resolved.parent != out_dir.resolve():
        raise InstallerGateError(f"ARTIFACT_ESCAPES_OUTPUT: {name!r}")
    if not resolved.is_file():
        raise InstallerGateError(f"ARTIFACT_MISSING: {item}")
    return item


def _validate_artifact_manifest(data: object, out_dir: Path) -> dict:
    """Strict fail-closed schema for INSTALLER_ARTIFACTS.json (H7-2)."""
    if not isinstance(data, dict) or set(data) != {"setup", "files"}:
        raise InstallerGateError("ARTIFACT_MANIFEST_SCHEMA: expected exactly setup + files")
    setup_name = data["setup"]
    files = data["files"]
    if not isinstance(files, list) or not files:
        raise InstallerGateError("ARTIFACT_MANIFEST_SCHEMA: files must be a non-empty list")
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256", "size"}:
            raise InstallerGateError(
                "ARTIFACT_MANIFEST_SCHEMA: each entry needs exactly name, sha256, size")
        item = _safe_artifact_path(out_dir, entry["name"])
        if entry["name"] in seen:
            raise InstallerGateError(f"ARTIFACT_DUPLICATE: {entry['name']!r}")
        seen.add(entry["name"])
        digest = entry["sha256"]
        if not (isinstance(digest, str) and _SHA256_RE.match(digest)):
            raise InstallerGateError(f"ARTIFACT_DIGEST_MALFORMED: {entry['name']!r}")
        size = entry["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise InstallerGateError(f"ARTIFACT_SIZE_INVALID: {entry['name']!r}")
        if item.stat().st_size != size:
            raise InstallerGateError(f"ARTIFACT_SIZE_MISMATCH: {entry['name']!r}")
    names = [entry["name"] for entry in files]
    if not isinstance(setup_name, str) or names[0] != setup_name:
        raise InstallerGateError(
            f"ARTIFACT_SETUP_MISMATCH: files[0]={names[0]!r} != setup={setup_name!r}")
    base = setup_name[:-4] if setup_name.lower().endswith(".exe") else setup_name
    expected = [f"{base}-{i}.bin" for i in range(1, len(names))]
    if names[1:] != expected:
        raise InstallerGateError(f"ARTIFACT_SLICES_NOT_CONTIGUOUS: {names[1:]}")
    return {"setup": setup_name, "files": files}


def load_installer_manifest(out_dir: Path, *, strict_extra: bool = True) -> dict:
    """Read the sealed artifact list and prove every entry still matches on disk.

    ``strict_extra`` also refuses anything else in the directory; publish turns it off
    because its own DIRTY_TREE gate owns that rule and reports it with its own reason."""
    path = out_dir / INSTALLER_MANIFEST
    if not path.is_file():
        raise InstallerGateError(f"ARTIFACT_MANIFEST_MISSING: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InstallerGateError(f"ARTIFACT_MANIFEST_MALFORMED: {path}: {e}") from e
    data = _validate_artifact_manifest(raw, out_dir)
    files = data["files"]
    names = [str(entry["name"]) for entry in files]
    for entry in files:
        item = out_dir / str(entry["name"])
        if _sha256_file(item) != entry["sha256"]:
            raise InstallerGateError(f"ARTIFACT_HASH_MISMATCH: {item}")
    if strict_extra:
        known = set(names) | {INSTALLER_MANIFEST, "release-manifest.json",
                              signing_gate.INTERNAL_MARKER}
        stray = sorted(p.name for p in out_dir.iterdir()
                       if p.is_file() and p.name not in known)
        if stray:
            raise InstallerGateError(f"STRAY_OUTPUT: {stray}")
    return data


def promote_installer_output(dist_premium: Path, next_dir: Path) -> Path:
    """Rollback-safe promote of a verified output dir to dist_premium/installer."""
    if not (next_dir / INSTALLER_MANIFEST).is_file():
        raise InstallerGateError(f"ARTIFACT_MANIFEST_MISSING: {next_dir}")
    load_installer_manifest(next_dir)  # names + hashes must still hold
    final = dist_premium / "installer"
    backup = dist_premium / f"installer.backup-{next_dir.name.split('-')[-1]}"
    if backup.exists():
        shutil.rmtree(backup)
    promoted = False
    try:
        if final.exists():
            os.rename(final, backup)
        os.rename(next_dir, final)
        promoted = True
    except BaseException:
        if promoted and final.exists():
            os.rename(final, next_dir)
        if backup.exists() and not final.exists():
            os.rename(backup, final)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    return final


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
        if args[0] == "seal-output":
            print(write_installer_manifest(Path(args[1]), args[2]))
            return 0
        if args[0] == "promote-output":
            print(promote_installer_output(Path(args[1]), Path(args[2])))
            return 0
        if args[0] == "verify-uninstaller":
            count = verify_installed_uninstaller(
                Path(args[1]), expected_thumbprint=args[2],
                inspector=signing_gate.powershell_inspector)
            print(f"verified {count} uninstaller(s)")
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
