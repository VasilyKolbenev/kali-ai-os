"""Base class for all skill templates."""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillTemplate(ABC):
    """Base class for skill templates.

    Provides data persistence and a standard interface for skill execution.
    Each skill instance gets isolated storage at data_dir/skills/{skill_name}/.
    """

    def __init__(self, skill_name: str, data_dir: Path) -> None:
        self.skill_name = skill_name
        self._data_path = data_dir / "skills" / skill_name
        self._data_path.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def template_name(self) -> str:
        """Return template identifier (e.g., 'tracker', 'monitor')."""

    @abstractmethod
    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a skill action with given config."""

    def _validate_filename(self, filename: str) -> Path:
        """Validate filename stays within skill data directory.

        Args:
            filename: Filename to validate.

        Returns:
            Resolved Path within the skill's data directory.

        Raises:
            ValueError: If the filename contains path traversal sequences or
                resolves outside the data directory.
        """
        if ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Invalid filename (path traversal blocked): {filename}")
        path = self._data_path / filename
        if not path.resolve().is_relative_to(self._data_path.resolve()):
            raise ValueError(f"Path escapes data directory: {path}")
        return path

    async def save_data(self, filename: str, data: Any) -> None:
        """Save JSON data to skill's storage directory.

        Args:
            filename: Name of the file to save within the skill's data directory.
            data: JSON-serializable data to persist.
        """
        path = self._validate_filename(filename)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    async def load_data(self, filename: str, default: Any = None) -> Any:
        """Load JSON data from skill's storage directory.

        Args:
            filename: Name of the file to load within the skill's data directory.
            default: Value to return if the file does not exist or fails to parse.

        Returns:
            Parsed JSON data or the default value.
        """
        path = self._validate_filename(filename)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", path, e)
            return default
