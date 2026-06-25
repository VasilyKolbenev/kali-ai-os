"""Tests for skill generation — esp. the free-text interval -> schedule keys
normalization that lets a voice-built time-based skill actually get a cron
registered (core-loop 3a)."""

import yaml

from kernel.builder.skill_generator import _with_schedule, generate_skill


def test_with_schedule_digit_hours() -> None:
    assert _with_schedule({"interval": "каждые 2 часа"})["reminders"] == {
        "enabled": True,
        "interval_hours": 2,
    }


def test_with_schedule_word_number() -> None:
    assert _with_schedule({"interval": "каждые два часа"})["reminders"]["interval_hours"] == 2


def test_with_schedule_every_hour() -> None:
    assert _with_schedule({"interval": "раз в час"})["reminders"]["interval_hours"] == 1


def test_with_schedule_minutes() -> None:
    assert _with_schedule({"interval": "каждые 30 минут"})["schedule"] == {"cron": "*/30 * * * *"}


def test_with_schedule_half_hour() -> None:
    assert _with_schedule({"interval": "полчаса"})["schedule"]["cron"] == "*/30 * * * *"


def test_with_schedule_preserves_structured() -> None:
    cfg = {"reminders": {"enabled": True, "interval_hours": 6}}
    assert _with_schedule(cfg) is cfg


def test_with_schedule_noop_without_interval() -> None:
    cfg = {"goal": "2 литра"}
    assert _with_schedule(cfg) == cfg


def test_generate_skill_writes_cron_keys(tmp_path) -> None:
    """End-to-end: a 'каждые 2 часа' tracker writes the nested keys the deployer
    reads from skill.yaml (previously it wrote a flat 'interval' string only)."""
    skill_dir = generate_skill(
        name="water-tracker",
        template="tracker",
        description="пить воду",
        config={"interval": "каждые 2 часа", "goal": "2 литра"},
        agents_dir=tmp_path,
    )
    data = yaml.safe_load((skill_dir / "skill.yaml").read_text(encoding="utf-8"))
    assert data["config"]["reminders"]["interval_hours"] == 2
