"""Life dashboard agent — tracks sleep, spending, energy."""

import os
import pathlib
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class LifeDashboardAgent(BaseAgent):
    """Agent for tracking daily life metrics: sleep, spending, energy."""

    def __init__(self) -> None:
        super().__init__()
        data_dir = os.environ.get("KALI_DATA_DIR")
        if data_dir:
            self._data_dir = pathlib.Path(data_dir) / "agents" / "life-dashboard"
            self._data_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily: dict[str, Any] = self._load_json(f"{today}.json") or {
            "date": today,
            "sleep": None,
            "spending": [],
            "energy": [],
        }

    def get_name(self) -> str:
        return "life-dashboard"

    def _save_daily(self) -> None:
        self._save_json(f"{self._daily['date']}.json", self._daily)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle life dashboard actions: log_sleep, log_spending, log_energy, get_daily_summary.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown.
        """
        if action == "log_sleep":
            self._daily["sleep"] = {
                "hours": args.get("hours", 0),
                "hrv": args.get("hrv", 0),
                "logged_at": datetime.now().isoformat(),
            }
            self._save_daily()
            return {"status": "logged", "sleep": self._daily["sleep"]}

        elif action == "log_spending":
            entry: dict[str, Any] = {
                "amount": args.get("amount", 0),
                "category": args.get("category", "other"),
                "logged_at": datetime.now().isoformat(),
            }
            self._daily.setdefault("spending", []).append(entry)
            self._save_daily()
            total = sum(e["amount"] for e in self._daily["spending"])
            return {"status": "logged", "entry": entry, "daily_total": total}

        elif action == "log_energy":
            energy_entry: dict[str, Any] = {
                "calories": args.get("calories", 0),
                "logged_at": datetime.now().isoformat(),
            }
            self._daily.setdefault("energy", []).append(energy_entry)
            self._save_daily()
            total = sum(e["calories"] for e in self._daily["energy"])
            return {"status": "logged", "entry": energy_entry, "daily_total": total}

        elif action == "get_daily_summary":
            sleep = self._daily.get("sleep")
            spending = self._daily.get("spending", [])
            energy = self._daily.get("energy", [])
            return {
                "date": self._daily["date"],
                "sleep_hours": sleep["hours"] if sleep else None,
                "sleep_hrv": sleep["hrv"] if sleep else None,
                "total_spending": sum(e["amount"] for e in spending),
                "total_calories": sum(e["calories"] for e in energy),
                "spending_count": len(spending),
                "energy_count": len(energy),
            }

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    LifeDashboardAgent().run()
