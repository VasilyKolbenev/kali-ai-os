"""Core-loop e2e: scheduled ``skill.{name}.trigger`` → execute → notify.

Closes the gap left by ``tests/kernel/test_main.py::TestScheduledSkillTrigger``,
which proves the *subscriber wiring* with a **MagicMock** executor (it only
asserts ``execute`` was awaited). This module instead drives the SUBSCRIBER →
execute → notify leg with a **real** :class:`~kernel.skill_executor.SkillExecutor`,
a **real** :class:`~kernel.notifications.NotificationManager`, and the **real**
``EventBus`` wired by the app's lifespan, proving:

    1. firing branch   — a real reminder skill whose window is open returns
       ``should_fire=True`` and the subscriber routes its REAL message into the
       NotificationManager queue, and
    2. suppression branch — a real reminder skill whose window is closed returns
       ``should_fire=False`` and NO notification is produced.

Determinism: the reminder template's ``_check`` is gated by the
``start_hour <= now.hour < end_hour`` window. We pin ``start_hour=0,
end_hour=24`` (open at every wall-clock hour) for the firing branch and
``start_hour=0, end_hour=0`` (empty at every wall-clock hour) for the
suppression branch — both are time-independent, so there is no wall-clock
flakiness. It is ML-free (template skills run in-process; no torch/F5/whisper).

The ``register_cron(topic="skill.{name}.trigger")`` assertion is already covered
by the keystone ``test_core_loop_build_deploy.py`` (assertion b) and is NOT
duplicated here — this test targets only the consumer side of that topic.

Wiring reuse: imports the real-lifespan ``app``/``client`` fixtures from
``tests/kernel/test_main.py`` rather than re-wiring the app by hand, so there is
no manual-wiring drift versus the rest of the suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from kernel.notifications import NotificationManager
from kernel.skill_executor import SkillExecutor

# Reuse the real-lifespan app fixture (and its async generator deps). The real
# lifespan is what subscribes ``event_bus.subscribe("skill.*", _on_skill_trigger)``
# and constructs the real SkillExecutor + NotificationManager on app.state.
from tests.kernel.test_main import app  # noqa: F401  (pytest fixture)


def _deploy_reminder_skill(
    application: Any,  # noqa: ANN401 — FastAPI app; .state is dynamically typed
    name: str,
    *,
    message: str,
    start_hour: int,
    end_hour: int,
) -> None:
    """Deploy a REAL reminder skill into the running app's executor + registry.

    Writes ``manifest.yaml`` + ``skill.yaml`` under the live plugin registry's
    ``agents_dir`` and loads them into the SAME real ``skill_executor`` /
    ``plugin_registry`` the lifespan created — mirroring the post-deploy
    ``load_skill`` + ``register_dir`` path (no MagicMock).

    Args:
        application: The running FastAPI application (real lifespan started).
        name: Skill directory name (becomes the skill name).
        message: Reminder text the skill should fire with.
        start_hour: Window start hour (0-23) passed to the reminder template.
        end_hour: Window end hour (0-24); window is ``start_hour <= h < end_hour``.
    """
    skill_dir: Path = application.state.plugin_registry.agents_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": name,
                "version": "1.0.0",
                "description": "Reminder skill under test",
                "protocol": "skill",
                "tools": [{"name": "check", "description": "Check", "parameters": {}}],
                "capabilities": [f"{name}.check"],
                "permissions": [],
            }
        ),
        encoding="utf-8",
    )
    (skill_dir / "skill.yaml").write_text(
        yaml.dump(
            {
                "template": "reminder",
                "display_name": name,
                "config": {
                    "message": message,
                    "interval_hours": 1,
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                },
            }
        ),
        encoding="utf-8",
    )
    # Load into the REAL executor + register into the REAL registry (the same
    # instances the subscriber reads from on app.state).
    application.state.skill_executor.load_skill(skill_dir)
    manifest = application.state.plugin_registry.register_dir(skill_dir)
    assert manifest is not None, f"register_dir rejected {skill_dir}"


@pytest.mark.core_loop
async def test_schedule_fire_runs_real_skill_and_notifies(app: Any) -> None:  # noqa: ANN401, F811
    """Open-window reminder: trigger fires the REAL skill → REAL notification."""
    s = app.state

    # Guard: these are the genuine components, not test doubles.
    assert isinstance(s.skill_executor, SkillExecutor)
    assert isinstance(s.notifications, NotificationManager)

    message = "Пора пить воду — real skill output"
    _deploy_reminder_skill(
        app, "rem-fire", message=message, start_hour=0, end_hour=24
    )
    # Sanity: the skill is genuinely loaded in the real executor.
    assert "rem-fire" in s.skill_executor.list_skills()

    before = len(s.notifications.get_pending())

    # Fire the cron topic directly on the REAL EventBus (bypass wall-clock).
    from kernel.models import Event

    await s.event_bus.publish(
        Event(topic="skill.rem-fire.trigger", source="test", payload={})
    )

    # The REAL skill ran and the REAL NotificationManager queued its message.
    pending = s.notifications.get_pending()
    assert len(pending) == before + 1, (
        f"expected exactly one new notification, got {len(pending) - before}"
    )
    fired = pending[-1]
    assert fired.message == message, (
        f"notification carries the REAL skill's message, got {fired.message!r}"
    )
    assert fired.source == "skill.rem-fire"
    assert fired.title == "rem-fire"

    # Prove it really came from the reminder template: the template records the
    # delivery in history.json (a side effect a mock would not produce).
    history = await s.skill_executor.execute("rem-fire", "history")
    assert any(
        e.get("message") == message for e in history.get("history", [])
    ), f"reminder template did not record the fire in history: {history!r}"


@pytest.mark.core_loop
async def test_schedule_fire_suppressed_when_skill_declines(app: Any) -> None:  # noqa: ANN401, F811
    """Closed-window reminder: ``should_fire=False`` → NO notification."""
    s = app.state
    assert isinstance(s.skill_executor, SkillExecutor)

    # Empty window (0 <= hour < 0 is False at EVERY hour) → deterministic decline.
    _deploy_reminder_skill(
        app, "rem-quiet", message="should never fire", start_hour=0, end_hour=0
    )
    assert "rem-quiet" in s.skill_executor.list_skills()

    # Confirm the REAL skill independently decides not to fire (no wall-clock luck).
    decision = await s.skill_executor.execute("rem-quiet", "check")
    assert decision.get("should_fire") is False, decision

    before = len(s.notifications.get_pending())

    from kernel.models import Event

    await s.event_bus.publish(
        Event(topic="skill.rem-quiet.trigger", source="test", payload={})
    )

    # Suppression honored: the subscriber produced no notification.
    assert len(s.notifications.get_pending()) == before, (
        "a should_fire=False skill must not produce a notification"
    )
