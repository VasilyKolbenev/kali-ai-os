"""Tests for YAML config manager with hot-reload."""

from pathlib import Path

import pytest
import yaml

from kernel.config_manager import ConfigManager, merge_patch
from kernel.models import ConfigSchema


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    config_file = tmp_path / "kali.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "server": {"host": "127.0.0.1", "port": 3005},
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
        assert config.server.port == 3005
        assert config.voice.wake_word == "jarvis"

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        manager = ConfigManager(tmp_path / "nonexistent.yaml")
        config = manager.load()
        assert config.server.port == 3005

    def test_load_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        manager = ConfigManager(empty)
        config = manager.load()
        assert config.server.port == 3005

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
        assert config.server.port == 3005

        path.write_text(yaml.dump({"server": {"port": 3000}}))
        config = manager.reload()
        assert config.server.port == 3000

    def test_config_property_returns_cached(self, config_dir: Path) -> None:
        manager = ConfigManager(config_dir / "kali.yaml")
        c1 = manager.config
        c2 = manager.config
        assert c1 is c2


class TestMergePatch:
    def test_replaces_scalar(self) -> None:
        assert merge_patch({"a": 1}, {"a": 2}) == {"a": 2}

    def test_adds_missing_key(self) -> None:
        assert merge_patch({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_null_removes_key(self) -> None:
        assert merge_patch({"a": 1, "b": 2}, {"a": None}) == {"b": 2}

    def test_recursive_merge_on_nested_dict(self) -> None:
        target = {"voice": {"wake_word": "jarvis", "mode": "wake_word"}}
        patch = {"voice": {"wake_word": "kali"}}
        assert merge_patch(target, patch) == {
            "voice": {"wake_word": "kali", "mode": "wake_word"}
        }

    def test_non_dict_patch_replaces_target(self) -> None:
        assert merge_patch({"a": 1}, "replaced") == "replaced"
        assert merge_patch({"a": 1}, [1, 2, 3]) == [1, 2, 3]

    def test_empty_patch_returns_copy_of_target(self) -> None:
        target = {"a": 1}
        result = merge_patch(target, {})
        assert result == target
        assert result is not target

    def test_does_not_mutate_target(self) -> None:
        target = {"voice": {"wake_word": "jarvis"}}
        merge_patch(target, {"voice": {"wake_word": "kali"}})
        assert target == {"voice": {"wake_word": "jarvis"}}


class TestConfigManagerSave:
    def test_save_writes_yaml_atomically(self, tmp_path: Path) -> None:
        path = tmp_path / "kali.yaml"
        manager = ConfigManager(path)
        manager.load()  # seed defaults
        config = ConfigSchema()
        config.voice.wake_word = "kali"

        manager.save(config)

        on_disk = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert on_disk["voice"]["wake_word"] == "kali"

    def test_save_returns_reloaded_cached_config(self, tmp_path: Path) -> None:
        path = tmp_path / "kali.yaml"
        manager = ConfigManager(path)
        manager.load()
        new_config = ConfigSchema()
        new_config.voice.wake_word = "kali"

        returned = manager.save(new_config)

        assert returned.voice.wake_word == "kali"
        assert manager.config.voice.wake_word == "kali"

    def test_save_creates_bak_from_prior_file(self, tmp_path: Path) -> None:
        path = tmp_path / "kali.yaml"
        prior_yaml = yaml.safe_dump({"voice": {"wake_word": "jarvis"}})
        path.write_text(prior_yaml, encoding="utf-8")

        manager = ConfigManager(path)
        manager.load()
        new_config = ConfigSchema()
        new_config.voice.wake_word = "kali"
        manager.save(new_config)

        backup = path.with_suffix(path.suffix + ".bak")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == prior_yaml

    def test_save_leaves_no_tempfile_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "kali.yaml"
        manager = ConfigManager(path)
        manager.load()
        manager.save(ConfigSchema())

        leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
        assert leftover == []

    def test_save_without_prior_file_skips_backup(self, tmp_path: Path) -> None:
        path = tmp_path / "kali.yaml"
        manager = ConfigManager(path)
        manager.save(ConfigSchema())

        backup = path.with_suffix(path.suffix + ".bak")
        assert not backup.exists()
