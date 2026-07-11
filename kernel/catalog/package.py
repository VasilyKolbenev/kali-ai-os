"""Package format (.kali-agent) — pack, unpack, inspect.

This is the Phase B canonical cloud-catalog format: a zip with per-file
``checksums.json`` and zip-slip-guarded extraction. A voice-built skill ships
only ``manifest.yaml`` + ``skill.yaml`` (no ``SKILL.md``); to keep the receiver's
strict ``SKILL.md`` loader happy, :func:`pack` synthesizes a spec-valid
``SKILL.md`` when absent — reusing the exact Phase A synthesis from
``kernel.skills.publisher`` so the two bundle formats agree byte-for-byte on
what the synthesized descriptor looks like.
"""

import hashlib
import json
import logging
import os
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_CHECKSUMS_FILE = "checksums.json"
_MANIFEST_FILE = "manifest.yaml"
_SKILL_MD_FILE = "SKILL.md"
_SKILL_YAML_FILE = "skill.yaml"


def _sha256(path: Path) -> str:
    """Compute SHA256 hex digest of a file.

    Args:
        path: File to hash.

    Returns:
        Hex string of SHA256 digest.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _synthesized_skill_md(agent_dir: Path) -> bytes | None:
    """Return synthesized SKILL.md bytes for a voice-built skill, else None.

    A voice-built skill (``skill.yaml`` present, ``SKILL.md`` absent) needs a
    spec-valid ``SKILL.md`` so the receiver's strict loader accepts the unpacked
    package. The synthesis is the Phase A one in ``kernel.skills.publisher`` —
    reused (not duplicated) so the .kali-agent zip and the .tar.gz P2P bundle
    carry an identical descriptor. SKILL.md-backed skills return None (packed
    verbatim, byte-identical to before).

    Args:
        agent_dir: The skill/agent directory being packed.

    Returns:
        The synthesized ``SKILL.md`` bytes, or None when no synthesis applies.
    """
    if (agent_dir / _SKILL_MD_FILE).is_file():
        return None
    if not (agent_dir / _SKILL_YAML_FILE).is_file():
        return None
    from kernel.skills.publisher import _synthesize_skill_md

    return _synthesize_skill_md(agent_dir)


def pack(agent_dir: Path, output_path: Path | None = None) -> Path:
    """Zip an agent/skill directory into a .kali-agent package.

    Includes all non-hidden files plus a generated checksums.json.

    Args:
        agent_dir: Directory containing the agent (must have manifest.yaml).
        output_path: Destination path for the package. Defaults to
            ``{agent_dir.name}.kali-agent`` in the current directory.

    Returns:
        Path to the created .kali-agent file.

    Raises:
        FileNotFoundError: If manifest.yaml is not found in agent_dir.
    """
    agent_dir = Path(agent_dir)
    manifest = agent_dir / _MANIFEST_FILE
    if not manifest.exists():
        raise FileNotFoundError(f"manifest.yaml not found in {agent_dir}")

    if output_path is None:
        output_path = Path.cwd() / f"{agent_dir.name}.kali-agent"
    output_path = Path(output_path)

    files = sorted(
        p for p in agent_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
    )

    checksums: dict[str, str] = {
        str(p.relative_to(agent_dir)): _sha256(p) for p in files
    }

    # Voice-built skills (skill.yaml, no SKILL.md): synthesize a spec-valid
    # SKILL.md (Phase A logic) so the receiver's strict loader accepts the
    # package; its checksum covers the synthesized bytes like any other member.
    synth_skill_md = _synthesized_skill_md(agent_dir)
    if synth_skill_md is not None:
        checksums[_SKILL_MD_FILE] = hashlib.sha256(synth_skill_md).hexdigest()

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            zf.write(file, file.relative_to(agent_dir))
        if synth_skill_md is not None:
            zf.writestr(_SKILL_MD_FILE, synth_skill_md)
        zf.writestr(_CHECKSUMS_FILE, json.dumps(checksums, indent=2))

    member_count = len(files) + (1 if synth_skill_md is not None else 0)
    logger.info("Packed %s → %s (%d files)", agent_dir.name, output_path, member_count)
    return output_path


def unpack(package_path: Path, target_dir: Path) -> Path:
    """Extract a .kali-agent package and verify checksums.

    Args:
        package_path: Path to the .kali-agent zip file.
        target_dir: Directory where the agent will be extracted.

    Returns:
        Path to the extracted agent directory (target_dir itself).

    Raises:
        FileNotFoundError: If checksums.json is missing from the archive.
        ValueError: If a member is not listed in checksums.json (or a listed
            member is absent), if a member path escapes ``target_dir``, or if
            any file's checksum does not match.
    """
    package_path = Path(package_path)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(package_path, "r") as zf:
        names = zf.namelist()
        if _CHECKSUMS_FILE not in names:
            raise FileNotFoundError(f"{_CHECKSUMS_FILE} missing from package")

        checksums: dict[str, str] = json.loads(zf.read(_CHECKSUMS_FILE))
        base = target_dir.resolve()

        # Zip-slip validation runs first (over every member) so a traversal
        # member is reported as a slip, not merely as an unlisted one.
        for info in zf.infolist():
            if info.filename == _CHECKSUMS_FILE:
                continue
            member = info.filename
            if Path(member).is_absolute() or os.path.isabs(member) or ".." in Path(member).parts:
                raise ValueError(f"Zip slip detected: {member}")
            target = (target_dir / member).resolve()
            if os.path.commonpath([str(target), str(base)]) != str(base):
                raise ValueError(f"Zip slip detected: {member}")

        # checksums.json is an EXHAUSTIVE manifest: the set of extractable file
        # members (everything but checksums.json and directory entries) must
        # equal the manifest keys. Reject any UNLISTED member before writing it
        # so an attacker cannot smuggle an extra file past checksum verification.
        expected_keys = {k.replace("\\", "/") for k in checksums}
        member_keys = {
            info.filename.replace("\\", "/")
            for info in zf.infolist()
            if info.filename != _CHECKSUMS_FILE and not info.is_dir()
        }
        extra = sorted(member_keys - expected_keys)
        if extra:
            raise ValueError(
                f"Members not listed in checksums.json: {', '.join(extra)}"
            )
        missing = sorted(expected_keys - member_keys)
        if missing:
            raise ValueError(
                f"Members listed in checksums.json but absent: {', '.join(missing)}"
            )

        for info in zf.infolist():
            if info.filename == _CHECKSUMS_FILE or info.is_dir():
                continue
            zf.extract(info, target_dir)

    for rel_path, expected in checksums.items():
        extracted = target_dir / rel_path
        actual = _sha256(extracted)
        if actual != expected:
            raise ValueError(
                f"Checksum mismatch for {rel_path}: expected {expected}, got {actual}"
            )

    logger.info("Unpacked %s → %s", package_path.name, target_dir)
    return target_dir


def get_package_info(package_path: Path) -> dict:
    """Read manifest.yaml from a .kali-agent package without extracting.

    Args:
        package_path: Path to the .kali-agent zip file.

    Returns:
        Parsed manifest contents as a dict.

    Raises:
        FileNotFoundError: If manifest.yaml is not present in the archive.
    """
    import yaml

    package_path = Path(package_path)
    with zipfile.ZipFile(package_path, "r") as zf:
        if _MANIFEST_FILE not in zf.namelist():
            raise FileNotFoundError(f"{_MANIFEST_FILE} missing from package")
        raw = zf.read(_MANIFEST_FILE)

    return yaml.safe_load(raw)
