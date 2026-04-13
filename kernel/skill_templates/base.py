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

    async def save_data(self, filename: str, data: Any) -> None:
        """Save JSON data to skill's storage directory.

        Args:
            filename: Name of the file to save within the skill's data directory.
            data: JSON-serializable data to persist.
        """
        path = self._data_path / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    async def load_data(self, filename: str, default: Any = None) -> Any:
        """Load JSON data from skill's storage directory.

        Args:
            filename: Name of the file to load within the skill's data directory.
            default: Value to return if the file does not exist or fails to parse.

        Returns:
            Parsed JSON data or the default value.
        """
        path = self._data_path / filename
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", path, e)
            return default
