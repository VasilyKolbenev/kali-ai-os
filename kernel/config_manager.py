"""YAML configuration manager with hot-reload support."""

import logging
from pathlib import Path

import yaml

from kernel.models import ConfigSchema

logger = logging.getLogger(__name__)


class ConfigManager:
    """Loads and caches YAML config, supports hot-reload.

    If the config file is missing or empty, returns defaults.
    Partial configs are merged with defaults via Pydantic.
    """

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._config: ConfigSchema | None = None

    def load(self) -> ConfigSchema:
        """Load config from YAML file. Returns defaults if file missing or empty."""
        data: dict = {}
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                logger.exception("Failed to parse config at %s, using defaults", self._path)

        self._config = ConfigSchema(**data)
        return self._config

    def reload(self) -> ConfigSchema:
        """Force reload config from disk."""
        logger.info("Reloading config from %s", self._path)
        return self.load()

    @property
    def config(self) -> ConfigSchema:
        """Return cached config, loading from disk on first access."""
        if self._config is None:
            self.load()
        assert self._config is not None
        return self._config
