"""Shared base class for native JSON-RPC agents."""

import json
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseAgent(ABC):
    """Base class for all native KALI agents.

    Subclasses implement get_name() and handle_action().
    The base handles JSON-RPC protocol, health, init, shutdown.
    """

    def __init__(self) -> None:
        self._start_time = time.time()
        self._config: dict[str, Any] = {}
        self._data_dir = Path(f"data/agents/{self.get_name()}")
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def get_name(self) -> str:
        """Return agent name."""

    @abstractmethod
    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a tool action. Raise ValueError for unknown actions."""

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a JSON-RPC request and return response."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                self._config = params.get("config", {})
                result: dict[str, Any] = {"status": "ok", "name": self.get_name()}
            elif method == "health":
                result = {
                    "status": "healthy",
                    "uptime_s": int(time.time() - self._start_time),
                    "name": self.get_name(),
                }
            elif method == "execute":
                action = params.get("action", "")
                args = params.get("args", {})
                result = self.handle_action(action, args)
            elif method == "shutdown":
                result = {"status": "ok"}
                response = {"jsonrpc": "2.0", "result": result, "id": request_id}
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                sys.exit(0)
            else:
                return {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                    "id": request_id,
                }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": str(e)},
                "id": request_id,
            }

        return {"jsonrpc": "2.0", "result": result, "id": request_id}

    def _validate_path(self, filename: str) -> Path:
        """Validate filename stays within agent data directory.

        Args:
            filename: Simple filename (no path separators).

        Returns:
            Resolved Path inside the agent's data directory.

        Raises:
            ValueError: If the filename contains path traversal sequences.
        """
        if ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Invalid filename (path traversal blocked): {filename}")
        path = self._data_dir / filename
        if not path.resolve().is_relative_to(self._data_dir.resolve()):
            raise ValueError(f"Path escapes data directory: {path}")
        return path

    def _load_json(self, filename: str) -> Any:
        """Load data from a JSON file in the agent's data directory.

        Args:
            filename: Simple filename (no path separators).

        Returns:
            Parsed JSON data, or None if the file does not exist.
        """
        path = self._validate_path(filename)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _save_json(self, filename: str, data: Any) -> None:
        """Save data to a JSON file in the agent's data directory.

        Args:
            filename: Simple filename (no path separators).
            data: JSON-serialisable data to persist.
        """
        path = self._validate_path(filename)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def http_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Send HTTP request through kernel proxy. Requires 'network' permission.

        Args:
            method: HTTP method (GET, POST, …).
            url: Target URL.
            **kwargs: Additional parameters forwarded to the network proxy.

        Returns:
            Dict with 'status' and 'body' on success, or 'error' on failure.
        """
        return self._rpc_call("network.request", {"method": method, "url": url, **kwargs})

    def _rpc_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call kernel RPC method via JSON-RPC.

        Args:
            method: RPC method name.
            params: Method parameters.

        Returns:
            Result dict from the kernel, or a dict containing 'error'.
        """
        import json as _json

        request = {"jsonrpc": "2.0", "method": method, "params": params, "id": 99999}
        sys.stdout.write(_json.dumps(request) + "\n")
        sys.stdout.flush()
        response_line = sys.stdin.readline()
        if not response_line:
            return {"error": "No response from kernel"}
        response = _json.loads(response_line.strip())
        if "error" in response:
            err = response["error"]
            return {"error": err.get("message", str(err)) if isinstance(err, dict) else str(err)}
        return response.get("result", {})

    def run(self) -> None:
        """Main loop — read JSON-RPC from stdin."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
            except json.JSONDecodeError:
                response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
