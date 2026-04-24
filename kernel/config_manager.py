"""YAML configuration manager with hot-reload support."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from kernel.models import ConfigSchema

logger = logging.getLogger(__name__)


def merge_patch(target: Any, patch: Any) -> Any:
    """Apply an RFC 7396 JSON Merge Patch to `target`.

    Merge semantics (per RFC 7396):
      - If `patch` is not a dict, it replaces `target` entirely.
      - If `patch` is a dict, each key is merged recursively into `target`.
      - A null value in `patch` removes the key from the result.
      - Missing keys in `patch` are preserved from `target`.

    Args:
        target: Current document (typically a dict from yaml.safe_load).
        patch: Patch document to merge on top.

    Returns:
        A new document with the patch applied. `target` is not mutated.
    """
    if not isinstance(patch, dict):
        return patch
    base: dict[str, Any] = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = merge_patch(base.get(key), value)
    return base


class ConfigManager:
    """Loads and caches YAML config, supports hot-reload and atomic save.

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

    def save(self, config: ConfigSchema) -> ConfigSchema:
        """Atomically persist config to YAML on disk.

        Creates `<path>.bak` from the current file (if present) before writing.
        Uses tempfile + os.replace for crash safety — readers never see a
        partially written file. Comments are lost (yaml.safe_dump limitation),
        which is acceptable for single-user local config. Hand-edits are
        recoverable from the `.bak` sibling.

        Args:
            config: Validated ConfigSchema instance to persist.

        Returns:
            The freshly reloaded ConfigSchema from disk (cache updated).
        """
        payload = config.model_dump()
        serialized = yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

        if self._path.exists():
            backup = self._path.with_suffix(self._path.suffix + ".bak")
            backup.write_bytes(self._path.read_bytes())

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".tmp_",
            suffix=self._path.suffix or ".yaml",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

        return self.reload()

    @property
    def config(self) -> ConfigSchema:
        """Return cached config, loading from disk on first access."""
        if self._config is None:
            self.load()
        assert self._config is not None
        return self._config
