"""SSRF-guard tests for the currency agent's ``_fetch_rates`` egress.

``agents/currency/agent.py`` ``_fetch_rates`` builds a URL from a
caller-supplied ``base`` currency code: ``f"{BASE_URL}/{base.upper()}"``
and makes a GET to ``open.er-api.com``. These tests assert that
``_fetch_rates`` routes egress through ``SandboxHttpClient`` (the
fail-closed guard: private-IP block + whitelist + redirect re-check)
rather than raw ``urllib.urlopen``:

- a private/loopback/metadata host is BLOCKED (no fetch, error dict
  returned, raw urllib never used);
- a normal ``open.er-api.com`` call routes through the guard and returns
  parsed JSON with the expected shape.

DNS note: private IP *literals* are parsed by ``ipaddress`` without any
DNS, so the SSRF-block test needs no network; the public-host test mocks
the guard's ``_resolves_to_private`` (real public hosts resolve to a
captive address here).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "currency" / "agent.py"
)


def _load_agent():
    """Import the currency agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("currency_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    return agent_mod.CurrencyAgent()


def _mock_opener_open(body: bytes, url: str = "https://open.er-api.com/v6/latest/USD"):
    """Mock for ``OpenerDirector.open`` — the guard fetches via its opener."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = url
    mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_resp)


class TestFetchRatesSsrfBlocked:
    @pytest.mark.parametrize(
        "host",
        [
            "169.254.169.254",
            "127.0.0.1",
            "10.0.0.5",
            "192.168.0.1",
        ],
    )
    def test_private_host_blocked(self, agent, agent_mod, host, monkeypatch):
        """A private/loopback host resolving from BASE_URL is BLOCKED.

        We patch BASE_URL on the loaded module so ``_fetch_rates`` builds a
        URL to a private IP; the guard must reject it without ever calling
        urllib's opener.
        """
        monkeypatch.setattr(agent_mod, "BASE_URL", f"https://{host}/v6/latest")
        with patch("urllib.request.OpenerDirector.open") as op:
            result = agent._fetch_rates("USD")
        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()


class TestFetchRatesGuarded:
    def test_normal_call_routes_through_guard_and_parses(self, agent):
        """A normal ``open.er-api.com`` call routes through the guard and
        returns parsed JSON.
        """
        payload = {
            "result": "success",
            "base_code": "USD",
            "rates": {"EUR": 0.92, "RUB": 88.5},
            "time_last_update_utc": "Mon, 01 Jan 2025 00:00:00 +0000",
        }
        body = json.dumps(payload).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ):
            result = agent._fetch_rates("USD")
        assert result["result"] == "success"
        assert result["base_code"] == "USD"
        assert "EUR" in result["rates"]

    def test_off_whitelist_host_blocked(self, agent, agent_mod, monkeypatch):
        """A BASE_URL pointing to a non-whitelisted public host is blocked."""
        monkeypatch.setattr(agent_mod, "BASE_URL", "https://evil.example.com/v6/latest")
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            result = agent._fetch_rates("USD")
        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()
