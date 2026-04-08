"""Smart home agent — Home Assistant integration stub."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class SmartHomeAgent(BaseAgent):
    """Stub agent returning mock device data. Real HA integration in v2."""

    def __init__(self) -> None:
        super().__init__()
        self._devices: list[dict[str, Any]] = [
            {
                "id": "light.living_room",
                "name": "Living Room Light",
                "state": "off",
                "type": "light",
            },
            {"id": "light.bedroom", "name": "Bedroom Light", "state": "off", "type": "light"},
            {"id": "climate.thermostat", "name": "Thermostat", "state": "22°C", "type": "climate"},
        ]

    def get_name(self) -> str:
        return "smart-home"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle smart home actions: get_devices, control_device, get_status.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown or device not found.
        """
        if action == "get_devices":
            return {"devices": self._devices, "count": len(self._devices)}

        elif action == "control_device":
            device_id = args.get("device_id", "")
            cmd = args.get("action", "toggle")
            for dev in self._devices:
                if dev["id"] == device_id:
                    if cmd in ("on", "off"):
                        dev["state"] = cmd
                    elif cmd == "toggle":
                        dev["state"] = "on" if dev["state"] == "off" else "off"
                    return {"status": "ok", "device": dev}
            raise ValueError(f"Device not found: {device_id}")

        elif action == "get_status":
            return {"devices": self._devices}

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    SmartHomeAgent().run()
