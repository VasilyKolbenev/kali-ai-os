"""Tests for SmartHomeAgent — Home Assistant integration."""

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import importlib.util
from pathlib import Path

import pytest

# smart-home directory has a hyphen — can't use normal import
_AGENT_PATH = Path(__file__).parent.parent / "agents" / "smart-home" / "agent.py"
_spec = importlib.util.spec_from_file_location("smart_home_agent", _AGENT_PATH)
assert _spec and _spec.loader, f"Could not load spec from {_AGENT_PATH}"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
SmartHomeAgent = _mod.SmartHomeAgent
_parse_ha_state = _mod._parse_ha_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HA_STATES = [
    {
        "entity_id": "light.living_room",
        "state": "off",
        "attributes": {"friendly_name": "Living Room Light"},
    },
    {
        "entity_id": "light.bedroom",
        "state": "on",
        "attributes": {"friendly_name": "Bedroom Light"},
    },
    {
        "entity_id": "switch.fan",
        "state": "off",
        "attributes": {"friendly_name": "Fan Switch"},
    },
    # non-device entity — must be filtered out
    {
        "entity_id": "sensor.temperature",
        "state": "21.5",
        "attributes": {"friendly_name": "Temperature"},
    },
]

_HA_LIGHT_STATE = {
    "entity_id": "light.living_room",
    "state": "on",
    "attributes": {"friendly_name": "Living Room Light", "brightness": 255},
}


def _make_agent(ha_url: str = "http://ha.local:8123", ha_token: str = "test-token") -> SmartHomeAgent:
    """Create agent with HA configured via environment patch."""
    with patch.dict(os.environ, {"HA_URL": ha_url, "HA_TOKEN": ha_token}):
        return SmartHomeAgent()


def _make_unconfigured_agent() -> SmartHomeAgent:
    """Create agent without HA configured."""
    env = {"HA_URL": "", "HA_TOKEN": ""}
    with patch.dict(os.environ, env):
        return SmartHomeAgent()


# ---------------------------------------------------------------------------
# Unit — _parse_ha_state
# ---------------------------------------------------------------------------


class TestParseHaState:
    def test_parse_ha_state_extracts_fields(self) -> None:
        state = {
            "entity_id": "light.test",
            "state": "on",
            "attributes": {"friendly_name": "Test Light"},
        }
        result = _parse_ha_state(state)
        assert result["id"] == "light.test"
        assert result["name"] == "Test Light"
        assert result["state"] == "on"
        assert result["type"] == "light"

    def test_parse_ha_state_falls_back_to_entity_id_for_name(self) -> None:
        state = {"entity_id": "switch.relay", "state": "off", "attributes": {}}
        result = _parse_ha_state(state)
        assert result["name"] == "switch.relay"


# ---------------------------------------------------------------------------
# get_devices — real HA path
# ---------------------------------------------------------------------------


class TestGetDevicesReal:
    def test_get_devices_returns_filtered_list(self) -> None:
        agent = _make_agent()
        agent.http_request = MagicMock(  # type: ignore[method-assign]
            return_value={"body": _HA_STATES}
        )

        result = agent.handle_action("get_devices", {})

        assert "devices" in result
        # sensor.temperature must be filtered out
        ids = [d["id"] for d in result["devices"]]
        assert "light.living_room" in ids
        assert "light.bedroom" in ids
        assert "switch.fan" in ids
        assert "sensor.temperature" not in ids

    def test_get_devices_count_matches_devices_len(self) -> None:
        agent = _make_agent()
        agent.http_request = MagicMock(return_value={"body": _HA_STATES})  # type: ignore[method-assign]

        result = agent.handle_action("get_devices", {})
        assert result["count"] == len(result["devices"])

    def test_get_devices_calls_ha_states_endpoint(self) -> None:
        agent = _make_agent()
        mock_http = MagicMock(return_value={"body": []})
        agent.http_request = mock_http  # type: ignore[method-assign]

        agent.handle_action("get_devices", {})

        mock_http.assert_called_once()
        call_args = mock_http.call_args
        assert call_args[0][0] == "GET"
        assert "/api/states" in call_args[0][1]


# ---------------------------------------------------------------------------
# control_device — real HA path
# ---------------------------------------------------------------------------


class TestControlDeviceReal:
    def _make_http_mock(self, state_after: dict[str, Any] | None = None) -> MagicMock:
        """Mock that returns empty body for service calls, state for state fetch."""
        state = state_after or _HA_LIGHT_STATE

        def side_effect(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            if method == "POST":
                return {"body": []}  # service call response
            # GET /api/states/<entity_id>
            return {"body": state}

        return MagicMock(side_effect=side_effect)

    def test_control_device_turn_on_light(self) -> None:
        agent = _make_agent()
        agent.http_request = self._make_http_mock()  # type: ignore[method-assign]

        result = agent.handle_action(
            "control_device", {"device_id": "light.living_room", "action": "on"}
        )

        assert result["status"] == "ok"
        assert result["device"]["id"] == "light.living_room"

    def test_control_device_posts_correct_service(self) -> None:
        agent = _make_agent()
        calls: list[tuple[Any, ...]] = []

        def capture(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            calls.append((method, url, kwargs))
            if method == "POST":
                return {"body": []}
            return {"body": _HA_LIGHT_STATE}

        agent.http_request = MagicMock(side_effect=capture)  # type: ignore[method-assign]

        agent.handle_action("control_device", {"device_id": "light.bedroom", "action": "off"})

        post_calls = [(m, u) for m, u, _ in calls if m == "POST"]
        assert len(post_calls) == 1
        assert "/services/homeassistant/turn_off" in post_calls[0][1]

    def test_control_device_toggle(self) -> None:
        agent = _make_agent()
        agent.http_request = self._make_http_mock()  # type: ignore[method-assign]

        result = agent.handle_action(
            "control_device", {"device_id": "light.living_room", "action": "toggle"}
        )

        assert result["status"] == "ok"

    def test_control_device_missing_device_id_raises(self) -> None:
        agent = _make_agent()
        agent.http_request = MagicMock(return_value={"body": []})  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="device_id is required"):
            agent.handle_action("control_device", {"action": "on"})

    def test_control_device_unknown_action_raises(self) -> None:
        agent = _make_agent()
        agent.http_request = MagicMock(return_value={"body": []})  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="Unsupported action"):
            agent.handle_action(
                "control_device", {"device_id": "light.x", "action": "explode"}
            )

    def test_control_device_set_temperature(self) -> None:
        agent = _make_agent()
        calls: list[tuple[Any, ...]] = []

        def capture(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            calls.append((method, url, kwargs))
            if method == "POST":
                return {"body": []}
            return {
                "body": {
                    "entity_id": "climate.thermostat",
                    "state": "heat",
                    "attributes": {"friendly_name": "Thermostat", "temperature": 23.0},
                }
            }

        agent.http_request = MagicMock(side_effect=capture)  # type: ignore[method-assign]

        result = agent.handle_action(
            "control_device",
            {"device_id": "climate.thermostat", "action": "set", "value": "23"},
        )

        assert result["status"] == "ok"
        post_calls = [(m, u, kw) for m, u, kw in calls if m == "POST"]
        assert "/services/climate/set_temperature" in post_calls[0][1]
        assert post_calls[0][2]["json"]["temperature"] == 23.0


# ---------------------------------------------------------------------------
# get_status — real HA path
# ---------------------------------------------------------------------------


class TestGetStatusReal:
    def test_get_status_single_entity(self) -> None:
        agent = _make_agent()
        agent.http_request = MagicMock(  # type: ignore[method-assign]
            return_value={"body": _HA_LIGHT_STATE}
        )

        result = agent.handle_action("get_status", {"entity_id": "light.living_room"})

        assert "device" in result
        assert result["device"]["id"] == "light.living_room"

    def test_get_status_no_entity_returns_all_devices(self) -> None:
        agent = _make_agent()
        agent.http_request = MagicMock(  # type: ignore[method-assign]
            return_value={"body": _HA_STATES}
        )

        result = agent.handle_action("get_status", {})

        assert "devices" in result or "device" in result


# ---------------------------------------------------------------------------
# Mock fallback — HA not configured
# ---------------------------------------------------------------------------


class TestMockFallback:
    def test_get_devices_returns_mock_when_not_configured(self) -> None:
        agent = _make_unconfigured_agent()

        result = agent.handle_action("get_devices", {})

        assert result.get("mock") is True
        assert len(result["devices"]) > 0

    def test_control_device_mock_toggle(self) -> None:
        agent = _make_unconfigured_agent()

        # Use a device that exists in mock data
        result = agent.handle_action(
            "control_device",
            {"device_id": "light.living_room", "action": "on"},
        )

        assert result["status"] == "ok"
        assert result.get("mock") is True
        assert result["device"]["state"] == "on"

    def test_control_device_mock_device_not_found_raises(self) -> None:
        agent = _make_unconfigured_agent()

        with pytest.raises(ValueError, match="Device not found"):
            agent.handle_action(
                "control_device",
                {"device_id": "light.nonexistent", "action": "on"},
            )

    def test_get_status_mock_returns_devices(self) -> None:
        agent = _make_unconfigured_agent()

        result = agent.handle_action("get_status", {})

        assert result.get("mock") is True
        assert "devices" in result

    def test_get_status_mock_single_entity(self) -> None:
        agent = _make_unconfigured_agent()

        result = agent.handle_action("get_status", {"entity_id": "climate.thermostat"})

        assert result.get("mock") is True
        assert result["device"]["id"] == "climate.thermostat"

    def test_no_http_calls_when_not_configured(self) -> None:
        """Ensure http_request is never called when HA not configured."""
        agent = _make_unconfigured_agent()
        agent.http_request = MagicMock()  # type: ignore[method-assign]

        agent.handle_action("get_devices", {})

        agent.http_request.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


class TestUnknownAction:
    def test_unknown_action_raises(self) -> None:
        agent = _make_unconfigured_agent()

        with pytest.raises(ValueError, match="Unknown action"):
            agent.handle_action("fly_to_moon", {})
