"""HTTP REST protocol — communicates with agents via HTTP API."""

import logging
from typing import Any

import httpx

from kernel.agent_runtime.protocols.base import AgentProtocol

logger = logging.getLogger(__name__)


class HttpProtocol(AgentProtocol):
    """Communicates with HTTP-based agents."""

    def __init__(
        self,
        agent_name: str,
        base_url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = headers or {}
        self._client: httpx.AsyncClient | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout, headers=self._headers,
        )
        self._running = True
        logger.info("HTTP agent '%s' connected at %s", self.agent_name, self.base_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._running = False

    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/initialize", config)

    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/execute", {"action": action, "args": args})

    async def health(self) -> dict[str, Any]:
        if not self._client:
            return {"status": "disconnected"}
        try:
            resp = await self._client.get("/health")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def shutdown(self) -> None:
        try:
            await self._post("/shutdown", {})
        except Exception:
            pass

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError(f"Agent '{self.agent_name}' not connected")
        resp = await self._client.post(path, json=data)
        resp.raise_for_status()
        return resp.json()
