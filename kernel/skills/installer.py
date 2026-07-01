"""Install SKILL.md-based skills from remote GitHub sources into user AppData.

Flow:
    CatalogEntry → download tarball → extract → validate → safety gate → deploy

Safety:
- Validates SKILL.md frontmatter before install
- If skill has scripts/, each .py file goes through kernel.builder.safety_gate
- Refuses install if any script fails AST safety check
- Atomic install: writes to temp dir, moves on success, cleans on failure

Target location:
    %APPDATA%/KALI/skills/<skill-name>/  (overrides built-in if same name)
"""

from __future__ import annotations

import base64
import io
import logging
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from kernel.runtime_paths import appdata_dir
from kernel.skills.catalog import CatalogEntry, CatalogFetchError
from kernel.skills.loader import load_skill
from kernel.skills.validator import ValidationError

logger = logging.getLogger(__name__)


class InstallError(RuntimeError):
    """Raised when a skill cannot be installed."""


@dataclass
class InstallResult:
    """Outcome of an install attempt."""

    ok: bool
    skill_name: str
    install_path: Path | None = None
    error: str | None = None
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


def user_skills_dir() -> Path:
    """Writable dir where installed skills live."""
    p = appdata_dir() / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safety_check_scripts(skill_dir: Path) -> list[str]:
    """Run AST safety gate over any Python scripts in the skill.

    Returns:
        List of safety issues. Empty list means safe to install.
    """
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return []

    try:
        from kernel.builder.safety_gate import check_code
    except ImportError:
        logger.warning("Safety gate unavailable — skipping script checks")
        return []

    issues: list[str] = []
    for py_file in scripts_dir.rglob("*.py"):
        try:
            code = py_file.read_text(encoding="utf-8")
            result = check_code(code)
            if not result.safe:
                for problem in result.issues:
                    issues.append(f"{py_file.name}: {problem}")
        except Exception as exc:
            issues.append(f"{py_file.name}: cannot read/parse ({exc})")

    return issues


def _download_repo_subtree(
    owner: str,
    repo: str,
    ref: str,
    subpath: str,
    dest_dir: Path,
    *,
    timeout: float = 60.0,
) -> Path:
    """Download a single subdirectory from GitHub via tarball.

    Why tarball not git clone:
    - No git executable required on user's machine
    - One HTTP request instead of many
    - Works in bundled PyInstaller environment

    Returns:
        Path to the extracted subdirectory.
    """
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    logger.info("Downloading %s", url)

    try:
        resp = requests.get(url, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        raise InstallError(f"Download failed: {exc}") from exc

    if resp.status_code != 200:
        raise InstallError(f"GitHub returned {resp.status_code} for {url}")

    buf = io.BytesIO()
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        buf.write(chunk)
    buf.seek(0)

    # GitHub tarballs have top-level dir like "{repo}-{ref}/..."
    # We want to extract only "{repo}-{ref}/{subpath}/*"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_subdir = dest_dir / subpath.rsplit("/", 1)[-1]

    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        members = tar.getmembers()
        if not members:
            raise InstallError("Tarball is empty")

        top_prefix = members[0].name.split("/", 1)[0] + "/"
        want_prefix = top_prefix + subpath.strip("/") + "/"

        containment_root = target_subdir.resolve()

        extracted = False
        for m in members:
            if not m.name.startswith(want_prefix):
                continue
            relative = m.name[len(want_prefix) :]
            if not relative:
                continue
            out_path = target_subdir / relative
            # Path-traversal containment: a malicious tarball can carry a member
            # like "skills/x/../../../../pwned.py". Resolve the destination and
            # refuse anything that escapes the extraction subtree.
            resolved = out_path.resolve()
            if resolved != containment_root and not resolved.is_relative_to(
                containment_root
            ):
                raise InstallError(
                    f"Tarball member escapes staging dir: {m.name}"
                )
            if m.isdir():
                out_path.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                out_path.parent.mkdir(parents=True, exist_ok=True)
                f = tar.extractfile(m)
                if f is not None:
                    with open(out_path, "wb") as out:
                        out.write(f.read())
                    extracted = True
            # Skip symlinks, devices, etc. for safety

        if not extracted:
            raise InstallError(
                f"Subpath '{subpath}' not found in {owner}/{repo}@{ref}"
            )

    return target_subdir


def _deploy_atomic(extracted_dir: Path, final_path: Path) -> None:
    """Move a staged skill dir to its final location atomically.

    Replaces an existing skill of the same name, rolling back on failure so a
    failed install never leaves the user without their previous version.
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        backup = final_path.with_name(final_path.name + ".old")
        if backup.exists():
            shutil.rmtree(backup)
        final_path.rename(backup)
        try:
            shutil.move(str(extracted_dir), str(final_path))
            shutil.rmtree(backup)
        except Exception:
            # Rollback to the backed-up version
            if final_path.exists():
                shutil.rmtree(final_path)
            backup.rename(final_path)
            raise
    else:
        shutil.move(str(extracted_dir), str(final_path))


def install_from_catalog(
    entry: CatalogEntry,
    *,
    target_dir: Path | None = None,
    allow_overwrite: bool = False,
    skip_safety: bool = False,
) -> InstallResult:
    """Install a skill from a remote catalog entry.

    Args:
        entry: CatalogEntry describing the remote skill.
        target_dir: Override install location (defaults to user_skills_dir()).
        allow_overwrite: If True, replace existing skill of same name.
        skip_safety: DANGEROUS — bypass AST safety gate. For testing only.

    Returns:
        InstallResult with status + details.
    """
    target_root = target_dir or user_skills_dir()
    final_path = target_root / entry.name

    if final_path.exists() and not allow_overwrite:
        return InstallResult(
            ok=False,
            skill_name=entry.name,
            error=f"Skill '{entry.name}' already installed at {final_path}. "
                  f"Pass allow_overwrite=True to replace.",
        )

    # Stage in temp dir for atomicity
    with tempfile.TemporaryDirectory(prefix=f"kali-skill-{entry.name}-") as tmp:
        staging = Path(tmp)
        try:
            extracted_dir = _download_repo_subtree(
                entry.repo_owner,
                entry.repo_name,
                entry.repo_ref,
                entry.skill_path,
                staging,
            )
        except InstallError as exc:
            return InstallResult(
                ok=False, skill_name=entry.name, error=str(exc),
            )

        # Validate SKILL.md
        try:
            manifest = load_skill(extracted_dir, source=f"catalog:{entry.source_id}", strict=True)
        except (FileNotFoundError, ValidationError) as exc:
            return InstallResult(
                ok=False, skill_name=entry.name,
                error=f"Downloaded skill is invalid: {exc}",
            )

        if manifest.name != entry.name:
            return InstallResult(
                ok=False, skill_name=entry.name,
                error=f"SKILL.md name '{manifest.name}' does not match catalog entry '{entry.name}'",
            )

        # Safety gate
        warnings: list[str] = []
        if not skip_safety:
            issues = _safety_check_scripts(extracted_dir)
            if issues:
                return InstallResult(
                    ok=False, skill_name=entry.name,
                    error=f"Safety check failed:\n- " + "\n- ".join(issues),
                )
        else:
            warnings.append("Safety gate skipped — unsafe install mode")

        # Deploy atomically
        _deploy_atomic(extracted_dir, final_path)

        logger.info("Installed skill '%s' → %s", entry.name, final_path)
        return InstallResult(
            ok=True, skill_name=entry.name,
            install_path=final_path, warnings=warnings,
        )


def install_from_bundle(
    bundle_b64: str,
    *,
    expected_name: str | None = None,
    target_dir: Path | None = None,
    allow_overwrite: bool = False,
    skip_safety: bool = False,
) -> InstallResult:
    """Install a skill from a base64url(.tar.gz) bundle — the P2P share path.

    The bundle layout matches ``publisher.package_skill``: a single top-level
    ``<name>/`` directory containing SKILL.md (+ optional references/assets).
    Shared bundles are declarative-only: a bundle carrying a ``scripts/`` dir is
    rejected outright (voice-built shared agents carry none). The AST safety gate
    is a best-effort screen, not a sandbox.

    Args:
        bundle_b64: base64url-encoded .tar.gz (padding optional).
        expected_name: if given, the bundle's SKILL.md name must match.
        target_dir: override install location (defaults to user_skills_dir()).
        allow_overwrite: replace an existing skill of the same name.
        skip_safety: DANGEROUS — bypass the AST safety gate (testing only).

    Returns:
        InstallResult with status + details.
    """
    name_hint = expected_name or "skill"

    try:
        padding = "=" * (-len(bundle_b64) % 4)
        raw = base64.urlsafe_b64decode(bundle_b64 + padding)
    except Exception as exc:
        return InstallResult(ok=False, skill_name=name_hint, error=f"Invalid bundle encoding: {exc}")

    target_root = target_dir or user_skills_dir()

    with tempfile.TemporaryDirectory(prefix="kali-bundle-") as tmp:
        staging = Path(tmp)
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                # filter="data" (PEP 706) blocks path traversal, absolute paths,
                # symlinks and special files — refuses an unsafe bundle outright.
                tar.extractall(staging, filter="data")
        except Exception as exc:
            return InstallResult(ok=False, skill_name=name_hint, error=f"Cannot read bundle: {exc}")

        subdirs = [d for d in staging.iterdir() if d.is_dir()]
        if len(subdirs) != 1:
            return InstallResult(
                ok=False, skill_name=name_hint,
                error="Bundle must contain exactly one skill directory",
            )
        extracted_dir = subdirs[0]

        # Policy: shared bundles are declarative-only. Voice-built shared agents
        # carry no scripts/ dir; the AST gate is a best-effort screen, not a
        # sandbox, so a bundle that ships executable scripts/ is refused outright
        # rather than run. This closes the arbitrary-code-exec surface on the P2P
        # share path.
        if (extracted_dir / "scripts").is_dir():
            return InstallResult(
                ok=False, skill_name=name_hint,
                error="scripts not permitted in shared bundles",
            )

        try:
            manifest = load_skill(extracted_dir, source="bundle", strict=True)
        except (FileNotFoundError, ValidationError) as exc:
            return InstallResult(ok=False, skill_name=name_hint, error=f"Bundle skill is invalid: {exc}")

        name = manifest.name
        if expected_name and expected_name != name:
            return InstallResult(
                ok=False, skill_name=name,
                error=f"Bundle name '{name}' does not match expected '{expected_name}'",
            )

        final_path = target_root / name
        if final_path.exists() and not allow_overwrite:
            return InstallResult(
                ok=False, skill_name=name,
                error=f"Skill '{name}' already installed. Pass overwrite=True to replace.",
            )

        warnings: list[str] = []
        if not skip_safety:
            issues = _safety_check_scripts(extracted_dir)
            if issues:
                return InstallResult(
                    ok=False, skill_name=name,
                    error="Safety check failed:\n- " + "\n- ".join(issues),
                )
        else:
            warnings.append("Safety gate skipped — unsafe install mode")

        try:
            _deploy_atomic(extracted_dir, final_path)
        except Exception as exc:
            return InstallResult(ok=False, skill_name=name, error=f"Deploy failed: {exc}")

        logger.info("Installed skill '%s' from bundle → %s", name, final_path)
        return InstallResult(ok=True, skill_name=name, install_path=final_path, warnings=warnings)


def uninstall(skill_name: str, *, target_dir: Path | None = None) -> bool:
    """Remove a user-installed skill.

    Args:
        skill_name: Name matching the skill directory.
        target_dir: Override install location.

    Returns:
        True if removed, False if not found.
    """
    target = (target_dir or user_skills_dir()) / skill_name
    if not target.exists():
        return False
    try:
        shutil.rmtree(target)
        logger.info("Uninstalled skill: %s", skill_name)
        return True
    except Exception:
        logger.exception("Failed to uninstall %s", skill_name)
        return False
