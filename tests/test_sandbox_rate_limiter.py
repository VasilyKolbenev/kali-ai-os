"""Tests for the sliding window rate limiter."""

import time
from unittest.mock import patch

import pytest

from kernel.sandbox.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_under_limit_allowed(self) -> None:
        rl = RateLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert rl.check("agent-a") is True

    def test_over_limit_blocked(self) -> None:
        rl = RateLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            rl.check("agent-a")
        assert rl.check("agent-a") is False

    def test_agents_isolated(self) -> None:
        rl = RateLimiter(max_requests=2, window_seconds=60.0)
        rl.check("agent-a")
        rl.check("agent-a")
        # agent-a is now at limit
        assert rl.check("agent-a") is False
        # agent-b should still be allowed
        assert rl.check("agent-b") is True

    def test_window_expires_old_requests(self) -> None:
        rl = RateLimiter(max_requests=2, window_seconds=1.0)

        base = 1000.0

        # First: fill at t=0
        with patch("kernel.sandbox.rate_limiter.time.monotonic", return_value=base):
            rl.check("agent-a")
            rl.check("agent-a")
            assert rl.check("agent-a") is False

        # After window passes (t=2.0), old timestamps should have expired
        with patch("kernel.sandbox.rate_limiter.time.monotonic", return_value=base + 2.0):
            assert rl.check("agent-a") is True

    def test_get_usage_under_limit(self) -> None:
        rl = RateLimiter(max_requests=10, window_seconds=60.0)
        rl.check("agent-a")
        rl.check("agent-a")
        usage = rl.get_usage("agent-a")
        assert usage["used"] == 2
        assert usage["limit"] == 10
        assert usage["window_seconds"] == 60.0

    def test_get_usage_unknown_agent_returns_zero(self) -> None:
        rl = RateLimiter(max_requests=10, window_seconds=60.0)
        usage = rl.get_usage("never-seen")
        assert usage["used"] == 0
        assert usage["limit"] == 10

    def test_get_usage_excludes_expired_timestamps(self) -> None:
        rl = RateLimiter(max_requests=10, window_seconds=1.0)
        base = 5000.0

        with patch("kernel.sandbox.rate_limiter.time.monotonic", return_value=base):
            rl.check("agent-a")
            rl.check("agent-a")

        # After window expires, usage should reflect only active requests
        with patch("kernel.sandbox.rate_limiter.time.monotonic", return_value=base + 2.0):
            usage = rl.get_usage("agent-a")
            assert usage["used"] == 0
