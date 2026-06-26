"""Publish KALI skills to the community catalog.

Publishing workflow:

1. **Validate** — SKILL.md must satisfy Agent Skills spec (name, description, etc)
2. **Safety gate** — scripts/ Python files pass AST static analysis
3. **Package** — create a .tar.gz bundle ready for PR submission
4. **Submit** — options depend on environment:
   - If `gh` CLI is available: offer PR to VasilyKolbenev/kali-skills
   - Else: produce bundle + human-readable instructions

We do NOT auto-push to GitHub without explicit user consent — the user must
either run `gh skill publish` themselves or submit the bundle via PR.

For convenience, `PublishResult` includes the target repo URL + file path so
the UI can offer one-click actions (copy path, open in browser).
"""

from __future__ import annotations

import io
import logging
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kernel.skills.loader import SkillManifest, load_skill
from kernel.skills.validator import ValidationError, validate_frontmatter

logger = logging.getLogger(__name__)

#: Default community catalog repo (receives PRs from publishers).
DEFAULT_CATALOG_REPO = "VasilyKolbenev/kali-skills"


@dataclass
class PublishResult:
    """Outcome of a publish attempt."""

    ok: bool
    skill_name: str
    bundle_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    safety_issues: list[str] = field(default_factory=list)
    #: URL of the target repo where the skill should be contributed.
    catalog_repo_url: str = ""
    #: Human-readable next steps (shown in UI / CLI).
    instructions: list[str] = field(default_factory=list)


def _publish_dir() -> Path:
    """Writable dir where .kali-skill bundles are produced."""
    from kernel.runtime_paths import appdata_dir
    p = appdata_dir() / "published"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _scan_scripts_safety(skill_dir: Path) -> list[str]:
    """Run AST safety gate over any scripts. Returns list of issues."""
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return []

    try:
        from kernel.builder.safety_gate import check_code
    except ImportError:
        return ["safety_gate unavailable — scripts not scanned"]

    issues: list[str] = []
    for py_file in scripts_dir.rglob("*.py"):
        try:
            code = py_file.read_text(encoding="utf-8")
            result = check_code(code)
            if not result.safe:
                for problem in result.issues:
                    issues.append(f"{py_file.name}: {problem}")
        except Exception as exc:  # pragma: no cover
            issues.append(f"{py_file.name}: cannot analyze ({exc})")
    return issues


def _bundle_size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def validate_skill(skill_dir: Path | str) -> tuple[SkillManifest | None, list[str], list[str]]:
    """Validate a skill directory without creating a bundle.

    Returns:
        (manifest, errors, warnings). manifest is None on fatal errors.
    """
    skill_dir = Path(skill_dir).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not skill_dir.is_dir():
        return None, [f"Skill directory not found: {skill_dir}"], []

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None, [f"SKILL.md missing in {skill_dir}"], []

    try:
        manifest = load_skill(skill_dir, source="local", strict=False)
    except Exception as exc:
        return None, [f"Failed to parse SKILL.md: {exc}"], []

    # Re-validate frontmatter in strict mode for publish-time reporting
    frontmatter = {
        "name": manifest.name,
        "description": manifest.description,
    }
    if manifest.license:
        frontmatter["license"] = manifest.license
    if manifest.compatibility:
        frontmatter["compatibility"] = manifest.compatibility
    if manifest.metadata:
        frontmatter["metadata"] = dict(manifest.metadata)
    if manifest.allowed_tools:
        frontmatter["allowed-tools"] = manifest.allowed_tools

    result = validate_frontmatter(frontmatter, expected_name=skill_dir.name)
    errors.extend(result.errors)
    warnings.extend(result.warnings)

    # Extra publish-specific checks
    if len(manifest.description) < 40:
        warnings.append(
            "description is short — publishers should use 40+ chars with "
            "when-to-use keywords for better discovery"
        )
    if not manifest.license:
        warnings.append("no license specified — publishers should add a license (MIT/Apache-2.0 recommended)")
    if len(manifest.body.strip()) < 50:
        warnings.append("SKILL.md body is very short — add instructions + examples for agents")

    return manifest, errors, warnings


def _read_manifest_meta(skill_dir: Path) -> str:
    """Best-effort description from manifest.yaml / skill.yaml (voice skills)."""
    for fname in ("manifest.yaml", "skill.yaml"):
        fpath = skill_dir / fname
        if fpath.is_file():
            try:
                data = yaml.safe_load(fpath.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if isinstance(data, dict) and data.get("description"):
                return str(data["description"])
    return ""


def _synthesize_skill_md(skill_dir: Path) -> bytes:
    """Build a minimal, spec-valid SKILL.md for a voice skill that ships only
    manifest.yaml + skill.yaml. The frontmatter ``name`` is the directory name so
    the receiver's ``load_skill(expected_name=dir)`` validates after extraction.
    """
    name = skill_dir.name
    description = _read_manifest_meta(skill_dir).strip()
    if not description:
        description = f"{name}: agent created in KALI by voice."
    description = description[:1024]  # spec cap — keep load_skill(strict=True) valid on import
    frontmatter = {"name": name, "description": description, "compatibility": "protocol=skill"}
    yaml_text = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip()
    body = f"# {name}\n\n{description}\n\n_Generated by the KALI voice builder._\n"
    return f"---\n{yaml_text}\n---\n\n{body}".encode("utf-8")


def _add_bundle_members(
    tar: tarfile.TarFile, skill_dir: Path, *, include_scripts: bool
) -> None:
    """Add a skill's files to an open tarball under the ``<name>/`` arcname.

    SKILL.md-based skills are packaged exactly as before. Voice-built skills
    (no SKILL.md) get a synthesized SKILL.md plus their manifest.yaml/skill.yaml
    so the imported skill is both spec-valid and runnable.
    """
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        tar.add(skill_md, arcname=f"{name}/SKILL.md")
    else:
        # Voice-built skills ship manifest.yaml + skill.yaml without a SKILL.md;
        # synthesize a spec-valid one so the existing SKILL.md loader/validator
        # accept the imported bundle (zero installer change), and carry the
        # config so it stays runnable. Gated here so SKILL.md publishes are
        # byte-identical to today.
        content = _synthesize_skill_md(skill_dir)
        info = tarfile.TarInfo(name=f"{name}/SKILL.md")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
        for fname in ("manifest.yaml", "skill.yaml"):
            fpath = skill_dir / fname
            if fpath.is_file():
                tar.add(fpath, arcname=f"{name}/{fname}")

    for subdir in ("references", "assets"):
        src = skill_dir / subdir
        if src.is_dir():
            tar.add(src, arcname=f"{name}/{subdir}")

    if include_scripts:
        scripts = skill_dir / "scripts"
        if scripts.is_dir():
            tar.add(scripts, arcname=f"{name}/scripts")


def package_skill(
    skill_dir: Path | str,
    *,
    output_dir: Path | None = None,
    include_scripts: bool = True,
) -> Path:
    """Create a .kali-skill.tar.gz bundle from a skill directory.

    Args:
        skill_dir: Source skill dir (SKILL.md synthesized from manifest.yaml if absent).
        output_dir: Where to write the tarball (defaults to published_dir()).
        include_scripts: Include scripts/ directory if present.

    Returns:
        Path to the created tarball.
    """
    skill_dir = Path(skill_dir).resolve()
    target_dir = output_dir or _publish_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bundle_name = f"{skill_dir.name}-{timestamp}.kali-skill.tar.gz"
    bundle_path = target_dir / bundle_name

    # Build the tarball: everything under skill_dir → arcname skill_dir.name/*
    with tarfile.open(bundle_path, "w:gz") as tar:
        _add_bundle_members(tar, skill_dir, include_scripts=include_scripts)

    return bundle_path


def publish_skill(
    skill_dir: Path | str,
    *,
    catalog_repo: str = DEFAULT_CATALOG_REPO,
    skip_safety: bool = False,
    include_scripts: bool = True,
    output_dir: Path | None = None,
) -> PublishResult:
    """End-to-end publish flow: validate, safety, package, produce instructions.

    This does NOT push to GitHub — it prepares a submission bundle and
    returns actionable steps for the user to open a pull request.

    Args:
        skill_dir: Directory containing SKILL.md to publish.
        catalog_repo: Target GitHub repo (owner/name) to receive the PR.
        skip_safety: Bypass AST safety gate (dangerous — testing only).
        include_scripts: Include scripts/ in the bundle.
        output_dir: Where to write the tarball.

    Returns:
        PublishResult with ``ok`` flag, bundle path, errors/warnings, and
        human-readable instructions.
    """
    skill_dir = Path(skill_dir).resolve()
    manifest, errors, warnings = validate_skill(skill_dir)

    result = PublishResult(
        ok=False,
        skill_name=skill_dir.name,
        errors=list(errors),
        warnings=list(warnings),
        catalog_repo_url=f"https://github.com/{catalog_repo}",
    )

    if manifest is None or errors:
        result.ok = False
        return result

    # Safety gate
    if not skip_safety:
        issues = _scan_scripts_safety(skill_dir)
        if issues:
            result.safety_issues = issues
            result.errors.append("Scripts failed safety check — see safety_issues")
            return result
    else:
        result.warnings.append("Safety gate skipped — do NOT publish scripts with untrusted patterns")

    # Package
    try:
        bundle = package_skill(
            skill_dir,
            output_dir=output_dir,
            include_scripts=include_scripts,
        )
    except Exception as exc:
        result.errors.append(f"Failed to package skill: {exc}")
        return result

    size_mb = _bundle_size_mb(bundle)
    if size_mb > 5:
        result.warnings.append(f"Bundle is large ({size_mb:.1f} MB) — prefer skills under 5 MB")

    result.bundle_path = bundle
    result.ok = True
    result.instructions = [
        f"1. Fork {result.catalog_repo_url}",
        f"2. Extract your bundle: {bundle.name}",
        f"   → target path in fork: skills/{manifest.name}/",
        f"3. Commit + open PR against {catalog_repo} main branch",
        f"4. KALI team reviews + merges (official skills get ✅ badge)",
    ]
    return result


def run_cli(args: list[str] | None = None) -> int:
    """`kali publish <skill_dir>` entry point.

    Returns POSIX exit code (0 success, non-zero on failure).
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="kali publish",
        description="Validate + package a KALI skill for submission to the community catalog",
    )
    parser.add_argument("skill_dir", type=Path, help="Path to the skill directory (contains SKILL.md)")
    parser.add_argument(
        "--catalog-repo", default=DEFAULT_CATALOG_REPO,
        help=f"Target catalog repo (default: {DEFAULT_CATALOG_REPO})",
    )
    parser.add_argument(
        "--skip-safety", action="store_true",
        help="DANGEROUS — skip AST safety gate",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Where to write the bundle (default: %APPDATA%/KALI/published)",
    )
    ns = parser.parse_args(args)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = publish_skill(
        ns.skill_dir,
        catalog_repo=ns.catalog_repo,
        skip_safety=ns.skip_safety,
        output_dir=ns.output_dir,
    )

    if result.warnings:
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)

    if not result.ok:
        print(f"FAILED to publish '{result.skill_name}':", file=sys.stderr)
        for e in result.errors:
            print(f"  - {e}", file=sys.stderr)
        for s in result.safety_issues:
            print(f"  [safety] {s}", file=sys.stderr)
        return 1

    print(f"✓ Packaged '{result.skill_name}'")
    print(f"  Bundle: {result.bundle_path}")
    print()
    print("Next steps:")
    for step in result.instructions:
        print(f"  {step}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(run_cli())
