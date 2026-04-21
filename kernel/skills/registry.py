"""Skills registry — hybrid discovery across bundled and user-installed skills.

Per VISION.md architecture:
- BUILTIN: bundled in installer (read-only, under install dir / _MEIPASS)
- USER: writable, under %APPDATA%/KALI/skills (cross-platform via runtime_paths)
- CATALOG: fetched from remote sources (Agent Skills registries on GitHub)

Discovery order: user → builtin (user-installed overrides bundled of same name).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from kernel.runtime_paths import appdata_dir, is_frozen, project_root
from kernel.skills.loader import SkillManifest, SkillParseError, load_skill
from kernel.skills.validator import ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillSource:
    """A root directory containing discoverable skill folders."""

    name: str           # "builtin", "user", etc.
    path: Path
    read_only: bool     # True for bundled, False for user-installed


def _builtin_skills_dir() -> Path:
    """Locate bundled skills directory (read-only, ships with installer)."""
    if is_frozen():
        import sys
        # PyInstaller: bundled data is alongside the exe or in _MEIPASS
        exe_dir = Path(sys.executable).parent
        candidates = [
            exe_dir / "skills",
            exe_dir / "_internal" / "skills",
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "skills")
        for p in candidates:
            if p.is_dir():
                return p
        return exe_dir / "skills"  # first-run default

    # Dev mode
    return project_root() / "skills"


def _user_skills_dir() -> Path:
    """User-writable skills directory (AppData / XDG data)."""
    return appdata_dir() / "skills"


def _legacy_agents_dir() -> Path:
    """Legacy agents/ dir with manifest.yaml — supported during migration."""
    if is_frozen():
        import sys
        exe_dir = Path(sys.executable).parent
        candidates = [
            exe_dir / "agents",
            exe_dir / "_internal" / "agents",
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "agents")
        for p in candidates:
            if p.is_dir():
                return p
        return exe_dir / "agents"
    return project_root() / "agents"


def default_sources() -> list[SkillSource]:
    """Return the standard skill sources in discovery order (user wins ties)."""
    sources: list[SkillSource] = []

    user_dir = _user_skills_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    sources.append(SkillSource(name="user", path=user_dir, read_only=False))

    builtin_dir = _builtin_skills_dir()
    if builtin_dir.is_dir():
        sources.append(SkillSource(name="builtin", path=builtin_dir, read_only=True))

    return sources


class SkillsRegistry:
    """Discovers and caches SKILL.md-based skills from multiple sources.

    Thread-safe for read operations. Reload must be called after mutations
    (install, uninstall).
    """

    def __init__(
        self,
        sources: list[SkillSource] | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """Construct a registry.

        Args:
            sources: List of SkillSource roots (defaults to built-in + user).
            strict: If True, discovery raises on malformed skills.
                    If False (default), log and skip.
        """
        self._sources = sources if sources is not None else default_sources()
        self._strict = strict
        self._manifests: dict[str, SkillManifest] = {}
        self._loaded = False

    @property
    def sources(self) -> list[SkillSource]:
        return list(self._sources)

    def discover(self) -> None:
        """Scan all sources and build the manifest index.

        User-installed skills take precedence over built-ins when names collide.
        Safe to call multiple times (idempotent reload).
        """
        self._manifests.clear()

        # Walk sources in reverse order so that earlier sources (user) override later (builtin)
        for source in reversed(self._sources):
            if not source.path.is_dir():
                continue
            for entry in sorted(source.path.iterdir()):
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                try:
                    manifest = load_skill(entry, source=source.name, strict=self._strict)
                    # Last writer wins — user source is processed last
                    self._manifests[manifest.name] = manifest
                except (SkillParseError, ValidationError) as exc:
                    logger.warning(
                        "Skipping malformed skill '%s' from %s: %s",
                        entry.name, source.name, exc,
                    )
                except Exception:
                    logger.exception(
                        "Unexpected error loading skill '%s' from %s",
                        entry.name, source.name,
                    )

        self._loaded = True
        logger.info(
            "Skills registry: %d skills from %d sources",
            len(self._manifests), len(self._sources),
        )

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.discover()

    def list_all(self) -> list[SkillManifest]:
        """All discovered skills, sorted by name."""
        self._ensure_loaded()
        return sorted(self._manifests.values(), key=lambda m: m.name)

    def get(self, name: str) -> SkillManifest | None:
        """Fetch a skill by name, or None if not found."""
        self._ensure_loaded()
        return self._manifests.get(name)

    def search(self, query: str) -> list[SkillManifest]:
        """Case-insensitive search by name or description.

        Intended for Agent Store UI. Rankings favour exact-name matches.
        """
        self._ensure_loaded()
        q = query.strip().lower()
        if not q:
            return self.list_all()

        exact: list[SkillManifest] = []
        name_match: list[SkillManifest] = []
        desc_match: list[SkillManifest] = []

        for m in self._manifests.values():
            name_lower = m.name.lower()
            if name_lower == q:
                exact.append(m)
            elif q in name_lower:
                name_match.append(m)
            elif q in m.description.lower():
                desc_match.append(m)

        return exact + name_match + desc_match

    def reload(self) -> None:
        """Force a full rediscovery (e.g. after install/uninstall)."""
        self._loaded = False
        self.discover()
