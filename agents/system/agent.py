"""System agent — time, timers, system information."""

import os
import platform
import shutil
import sys
import subprocess
import psutil
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class SystemAgent(BaseAgent):
    """Agent for system information, time queries, and timers."""

    def __init__(self) -> None:
        super().__init__()
        self._timers: list[dict[str, Any]] = []

    def get_name(self) -> str:
        return "system"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle system actions: get_time, get_system_info, set_timer.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown.
        """
        if action == "get_time":
            now = datetime.now()
            return {
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "weekday": now.strftime("%A"),
                "timezone": str(now.astimezone().tzinfo),
            }
        elif action == "get_system_info":
            total, used, free = shutil.disk_usage("/")
            
            # Get RAM info
            ram = psutil.virtual_memory()
            ram_total_gb = round(ram.total / (1024**3), 1)
            ram_used_gb = round(ram.used / (1024**3), 1)
            ram_percent = ram.percent
            
            # Get GPU info (NVIDIA)
            gpu_info = "N/A"
            try:
                # Try nvidia-smi for RTX 5070 / NVIDIA GPUs
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.stdout.strip():
                    parts = [p.strip() for p in result.stdout.strip().split(",")]
                    if len(parts) >= 4:
                        gpu_info = f"{parts[0]} (Load: {parts[1]}%, VRAM: {parts[2]}/{parts[3]} MB)"
            except Exception:
                pass
                
            return {
                "platform": platform.system(),
                "python_version": platform.python_version(),
                "processor": platform.processor(),
                "disk_free_gb": round(free / (1024**3), 1),
                "ram_total_gb": ram_total_gb,
                "ram_used_gb": ram_used_gb,
                "ram_percent": ram_percent,
                "gpu": gpu_info,
            }
        elif action == "set_timer":
            seconds = args.get("seconds", 60)
            label = args.get("label", "Timer")
            timer = {
                "seconds": seconds,
                "label": label,
                "set_at": datetime.now().isoformat(),
            }
            self._timers.append(timer)
            return {"status": "timer_set", "label": label, "seconds": seconds}
        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    SystemAgent().run()
