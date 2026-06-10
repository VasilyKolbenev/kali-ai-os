"""Package format (.kali-agent) — pack, unpack, inspect."""

import hashlib
import json
import logging
import os
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_CHECKSUMS_FILE = "checksums.json"
_MANIFEST_FILE = "manifest.yaml"


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

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            zf.write(file, file.relative_to(agent_dir))
        zf.writestr(_CHECKSUMS_FILE, json.dumps(checksums, indent=2))

    logger.info("Packed %s → %s (%d files)", agent_dir.name, output_path, len(files))
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
        ValueError: If any file's checksum does not match.
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
        for info in zf.infolist():
            if info.filename == _CHECKSUMS_FILE:
                continue
            # Zip slip protection: reject absolute or traversal member names,
            # then require the resolved target to be contained in target_dir.
            member = info.filename
            if Path(member).is_absolute() or os.path.isabs(member) or ".." in Path(member).parts:
                raise ValueError(f"Zip slip detected: {member}")
            target = (target_dir / member).resolve()
            if os.path.commonpath([str(target), str(base)]) != str(base):
                raise ValueError(f"Zip slip detected: {member}")
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
