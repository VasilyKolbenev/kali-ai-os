"""Native JSON-RPC protocol — communicates with agents via stdin/stdout."""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kernel.agent_runtime.protocols.base import AgentProtocol

if TYPE_CHECKING:
    from kernel.sandbox.network_proxy import NetworkProxy

logger = logging.getLogger(__name__)


class NativeProtocol(AgentProtocol):
    """Communicates with agent subprocesses via stdin/stdout JSON-RPC 2.0."""

    def __init__(self, agent_name: str, script_path: Path) -> None:
        self.agent_name = agent_name
        self._script_path = script_path
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._network_proxy: NetworkProxy | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    def set_network_proxy(self, proxy: "NetworkProxy") -> None:
        """Wire in a NetworkProxy to handle agent network.request calls."""
        self._network_proxy = proxy

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if self.is_running:
            return
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self._script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("Agent '%s' started (pid=%d)", self.agent_name, self._process.pid)
        # Drain stderr continuously: an agent that logs heavily would otherwise
        # fill the OS pipe buffer (~64 KB on Windows), block on its next write,
        # and deadlock — stdout would never be read. Matters at launch because
        # agents are user-generated.
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        """Consume the agent's stderr line-by-line (logged at debug) until EOF.

        Cancelled by ``stop()``; swallows pipe errors that occur when the
        process exits mid-read.
        """
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            # Read raw chunks, not lines: an agent can emit a huge line with no
            # newline, which readline() rejects at its 64 KB limit — leaving the
            # rest of the pipe unread and re-introducing the deadlock.
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break  # EOF — process closed stderr
                text = chunk.decode(errors="replace").rstrip()
                if text:
                    logger.debug("[%s stderr] %s", self.agent_name, text)
        except (BrokenPipeError, ConnectionResetError, ValueError):
            pass  # process exited / pipe closed mid-read

    async def stop(self) -> None:
        if not self.is_running:
            return
        try:
            await self.shutdown()
        except Exception:
            pass
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None
        self._process = None
        logger.info("Agent '%s' stopped", self.agent_name)

    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self._send("initialize", {"config": config})

    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._send("execute", {"action": action, "args": args})

    async def health(self) -> dict[str, Any]:
        return await self._send("health", {})

    async def shutdown(self) -> None:
        try:
            await self._send("shutdown", {})
        except Exception:
            pass

    async def _send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.is_running or not self._process:
            raise RuntimeError(f"Agent '{self.agent_name}' is not running")

        async with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": self._request_id,
            }
            line = json.dumps(request) + "\n"

            assert self._process.stdin is not None
            assert self._process.stdout is not None

            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

            while True:
                response_line = await asyncio.wait_for(
                    self._process.stdout.readline(), timeout=10.0
                )

                if not response_line:
                    raise RuntimeError(f"Agent '{self.agent_name}' closed stdout")

                response = json.loads(response_line.decode().strip())

                # Check if this is a reverse RPC from agent (has "method" instead of "result")
                if "method" in response and response["method"] == "network.request":
                    if self._network_proxy:
                        result = await self._network_proxy.handle(
                            self.agent_name, response.get("params", {})
                        )
                    else:
                        result = {"error": "NetworkProxy not available"}
                    rpc_response = (
                        json.dumps({"jsonrpc": "2.0", "result": result, "id": response.get("id")})
                        + "\n"
                    )
                    self._process.stdin.write(rpc_response.encode())
                    await self._process.stdin.drain()
                    continue

                if "error" in response:
                    raise RuntimeError(
                        f"Agent error: {response['error'].get('message', 'unknown')}"
                    )

                return response.get("result", {})
