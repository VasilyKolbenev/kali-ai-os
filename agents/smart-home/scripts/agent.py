"""Smart home agent — Home Assistant integration."""

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent

logger = logging.getLogger(__name__)

_MOCK_DEVICES: list[dict[str, Any]] = [
    {"id": "light.living_room", "name": "Living Room Light", "state": "off", "type": "light"},
    {"id": "light.bedroom", "name": "Bedroom Light", "state": "off", "type": "light"},
    {"id": "climate.thermostat", "name": "Thermostat", "state": "22", "type": "climate"},
]

_HA_ENTITY_TYPES = ("light.", "switch.", "climate.", "cover.", "fan.", "input_boolean.")

_ACTION_MAP: dict[str, tuple[str, str]] = {
    "on": ("homeassistant", "turn_on"),
    "off": ("homeassistant", "turn_off"),
    "toggle": ("homeassistant", "toggle"),
    "set": ("homeassistant", "turn_on"),  # domain overridden per entity type
}


def _entity_type(entity_id: str) -> str:
    """Extract type prefix from entity_id (e.g. 'light.x' -> 'light')."""
    return entity_id.split(".")[0] if "." in entity_id else "unknown"


def _parse_ha_state(state_obj: dict[str, Any]) -> dict[str, Any]:
    """Convert HA state object to agent device dict."""
    entity_id: str = state_obj.get("entity_id", "")
    attrs: dict[str, Any] = state_obj.get("attributes", {})
    return {
        "id": entity_id,
        "name": attrs.get("friendly_name", entity_id),
        "state": state_obj.get("state", "unknown"),
        "type": _entity_type(entity_id),
        "attributes": attrs,
    }


class SmartHomeAgent(BaseAgent):
    """Smart home agent with Home Assistant REST API integration.

    Falls back to mock data when HA_URL is not configured.
    """

    def __init__(self) -> None:
        super().__init__()
        self._ha_url: str = os.environ.get("HA_URL", "").rstrip("/")
        self._ha_token: str = os.environ.get("HA_TOKEN", "")

    def get_name(self) -> str:
        return "smart-home"

    def _ha_configured(self) -> bool:
        return bool(self._ha_url and self._ha_token)

    def _ha_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ha_token}",
            "Content-Type": "application/json",
        }

    def _ha_get(self, path: str) -> dict[str, Any]:
        """GET request to HA API. Returns parsed response body or raises RuntimeError."""
        url = f"{self._ha_url}/api{path}"
        result = self.http_request("GET", url, headers=self._ha_headers())
        if "error" in result:
            raise RuntimeError(f"HA request failed: {result['error']}")
        return result

    def _ha_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST request to HA API. Returns parsed response body or raises RuntimeError."""
        url = f"{self._ha_url}/api{path}"
        result = self.http_request("POST", url, headers=self._ha_headers(), json=body)
        if "error" in result:
            raise RuntimeError(f"HA request failed: {result['error']}")
        return result

    def _get_devices_real(self) -> dict[str, Any]:
        """Fetch and filter devices from HA /api/states."""
        response = self._ha_get("/states")
        states: list[Any] = response.get("body", [])
        devices = [
            _parse_ha_state(s)
            for s in states
            if isinstance(s, dict)
            and any(s.get("entity_id", "").startswith(t) for t in _HA_ENTITY_TYPES)
        ]
        return {"devices": devices, "count": len(devices)}

    def _control_device_real(self, device_id: str, cmd: str, value: str) -> dict[str, Any]:
        """Call HA service to control a device."""
        etype = _entity_type(device_id)

        if cmd not in _ACTION_MAP:
            raise ValueError(f"Unsupported action: {cmd}. Use on/off/toggle/set.")

        domain, service = _ACTION_MAP[cmd]

        # For 'set', pick the right domain + service
        if cmd == "set":
            if etype == "climate":
                domain, service = "climate", "set_temperature"
            elif etype == "light":
                domain, service = "light", "turn_on"
            else:
                domain, service = etype, "turn_on"

        body: dict[str, Any] = {"entity_id": device_id}
        if cmd == "set" and value:
            if etype == "climate":
                try:
                    body["temperature"] = float(value)
                except ValueError:
                    raise ValueError(f"Invalid temperature value: {value}")
            elif etype == "light":
                try:
                    body["brightness"] = int(value)
                except ValueError:
                    raise ValueError(f"Invalid brightness value: {value}")

        self._ha_post(f"/services/{domain}/{service}", body)

        # Fetch updated state
        state_response = self._ha_get(f"/states/{device_id}")
        device = _parse_ha_state(state_response.get("body", {}))
        return {"status": "ok", "device": device}

    def _get_status_real(self, entity_id: str) -> dict[str, Any]:
        """Fetch state for a single entity from HA."""
        state_response = self._ha_get(f"/states/{entity_id}")
        body = state_response.get("body", {})
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected HA response for {entity_id}")
        return _parse_ha_state(body)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle smart home actions: get_devices, control_device, get_status.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown or arguments are invalid.
        """
        if action == "get_devices":
            if not self._ha_configured():
                logger.warning("HA not configured (HA_URL/HA_TOKEN missing) — using mock data")
                return {"devices": _MOCK_DEVICES, "count": len(_MOCK_DEVICES), "mock": True}
            return self._get_devices_real()

        elif action == "control_device":
            device_id = args.get("device_id", "")
            cmd = args.get("action", "toggle")
            value = str(args.get("value", ""))
            if not device_id:
                raise ValueError("device_id is required")

            if not self._ha_configured():
                logger.warning("HA not configured — using mock data")
                for dev in _MOCK_DEVICES:
                    if dev["id"] == device_id:
                        if cmd in ("on", "off"):
                            dev["state"] = cmd
                        elif cmd == "toggle":
                            dev["state"] = "on" if dev["state"] == "off" else "off"
                        return {"status": "ok", "device": dict(dev), "mock": True}
                raise ValueError(f"Device not found: {device_id}")

            return self._control_device_real(device_id, cmd, value)

        elif action == "get_status":
            entity_id = args.get("entity_id", "")

            if not self._ha_configured():
                logger.warning("HA not configured — using mock data")
                if entity_id:
                    for dev in _MOCK_DEVICES:
                        if dev["id"] == entity_id:
                            return {"device": dict(dev), "mock": True}
                    raise ValueError(f"Device not found: {entity_id}")
                return {"devices": list(_MOCK_DEVICES), "mock": True}

            if entity_id:
                device = self._get_status_real(entity_id)
                return {"device": device}

            # No entity_id — return all filtered devices (same as get_devices)
            return self._get_devices_real()

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    SmartHomeAgent().run()
