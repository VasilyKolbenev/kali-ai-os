"""In-process agent protocol — runs agents as Python modules, no subprocess.

Used in frozen (PyInstaller) mode where sys.executable is the bundled exe,
so create_subprocess_exec(sys.executable, agent.py) would fork-bomb.

This protocol imports the agent class directly and calls handle_action().
All agents run in the same Python process as the kernel.
"""

import importlib.util
import logging
from pathlib import Path
from typing import Any

from kernel.agent_runtime.protocols.base import AgentProtocol

logger = logging.getLogger(__name__)


class InProcessProtocol(AgentProtocol):
    """Runs an agent as a Python module in the same process as the kernel."""

    def __init__(self, agent_name: str, script_path: Path) -> None:
        self.agent_name = agent_name
        self._script_path = script_path
        self._agent_instance: Any | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        # Dynamically import the agent module
        spec = importlib.util.spec_from_file_location(
            f"agents.{self.agent_name}.agent", self._script_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load agent spec: {self._script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find the agent class (subclass of BaseAgent)
        from agents._base.agent_base import BaseAgent
        agent_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseAgent)
                and attr is not BaseAgent
            ):
                agent_class = attr
                break

        if agent_class is None:
            raise RuntimeError(f"No BaseAgent subclass in {self._script_path}")

        self._agent_instance = agent_class()
        self._running = True
        logger.info("Agent '%s' started in-process", self.agent_name)

    async def stop(self) -> None:
        self._running = False
        self._agent_instance = None
        logger.info("Agent '%s' stopped", self.agent_name)

    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]:
        if not self._running or not self._agent_instance:
            raise RuntimeError(f"Agent '{self.agent_name}' not started")
        # BaseAgent's initialize() is called once; store config if needed
        if hasattr(self._agent_instance, "initialize"):
            result = self._agent_instance.initialize(config)
            return result if isinstance(result, dict) else {"status": "ok"}
        return {"status": "ok"}

    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self._running or not self._agent_instance:
            raise RuntimeError(f"Agent '{self.agent_name}' not started")
        result = self._agent_instance.handle_action(action, args)
        return result if isinstance(result, dict) else {"result": result}

    async def health(self) -> dict[str, Any]:
        return {"status": "healthy" if self._running else "stopped"}

    async def shutdown(self) -> None:
        await self.stop()
