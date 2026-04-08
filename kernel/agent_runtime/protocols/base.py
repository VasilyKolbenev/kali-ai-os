"""Base protocol interface for agent communication."""

import abc
from typing import Any


class AgentProtocol(abc.ABC):
    """Abstract base for agent communication protocols."""

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def health(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def shutdown(self) -> None: ...

    @property
    @abc.abstractmethod
    def is_running(self) -> bool: ...
