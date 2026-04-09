"""Tests for YAML config manager with hot-reload."""

from pathlib import Path

import pytest
import yaml

from kernel.config_manager import ConfigManager
from kernel.models import ConfigSchema


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    config_file = tmp_path / "kali.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "server": {"host": "127.0.0.1", "port": 8000},
                "voice": {"wake_word": "jarvis"},
            }
        )
    )
    return tmp_path


class TestConfigManager:
    def test_load_config(self, config_dir: Path) -> None:
        manager = ConfigManager(config_dir / "kali.yaml")
        config = manager.load()
        assert isinstance(config, ConfigSchema)
        assert config.server.port == 8000
        assert config.voice.wake_word == "jarvis"

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        manager = ConfigManager(tmp_path / "nonexistent.yaml")
        config = manager.load()
        assert config.server.port == 8000

    def test_load_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        manager = ConfigManager(empty)
        config = manager.load()
        assert config.server.port == 8000

    def test_load_partial_config_merges_defaults(self, tmp_path: Path) -> None:
        partial = tmp_path / "partial.yaml"
        partial.write_text(yaml.dump({"server": {"port": 9999}}))
        manager = ConfigManager(partial)
        config = manager.load()
        assert config.server.port == 9999
        assert config.server.host == "127.0.0.1"
        assert config.voice.wake_word == "jarvis"

    def test_reload_picks_up_changes(self, config_dir: Path) -> None:
        path = config_dir / "kali.yaml"
        manager = ConfigManager(path)
        config = manager.load()
        assert config.server.port == 8000

        path.write_text(yaml.dump({"server": {"port": 3000}}))
        config = manager.reload()
        assert config.server.port == 3000

    def test_config_property_returns_cached(self, config_dir: Path) -> None:
        manager = ConfigManager(config_dir / "kali.yaml")
        c1 = manager.config
        c2 = manager.config
        assert c1 is c2
