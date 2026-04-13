"""Per-agent rate limiter using sliding window."""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding window rate limiter per agent."""

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0) -> None:
        """Initialise the rate limiter.

        Args:
            max_requests: Maximum requests allowed in the window.
            window_seconds: Duration of the sliding window in seconds.
        """
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}

    def check(self, agent_name: str) -> bool:
        """Check if a request is allowed. Appends timestamp when allowed.

        Args:
            agent_name: Unique agent identifier.

        Returns:
            True if the request is under the rate limit and was recorded.
        """
        now = time.monotonic()
        timestamps = self._requests.setdefault(agent_name, [])
        cutoff = now - self._window
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= self._max:
            logger.warning("Rate limit exceeded for agent '%s'", agent_name)
            return False
        timestamps.append(now)
        return True

    def get_usage(self, agent_name: str) -> dict[str, Any]:
        """Return current usage statistics for an agent.

        Args:
            agent_name: Unique agent identifier.

        Returns:
            Dict with keys: used, limit, window_seconds.
        """
        now = time.monotonic()
        timestamps = self._requests.get(agent_name, [])
        cutoff = now - self._window
        active = [t for t in timestamps if t > cutoff]
        return {"used": len(active), "limit": self._max, "window_seconds": self._window}
