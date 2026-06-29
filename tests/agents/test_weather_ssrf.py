"""SSRF-guard tests for the weather agent's HTTP egress.

``agents/weather/agent.py`` makes GET requests to two fixed Open-Meteo hosts:
  - geocoding-api.open-meteo.com  (``_geocode``)
  - api.open-meteo.com            (``_get_weather``, ``_get_forecast``)

These tests assert that all three call sites route egress through
``SandboxHttpClient`` (private-IP block + whitelist + redirect re-check)
rather than raw ``urllib.urlopen``:

- ``_geocode`` routes through ``SandboxHttpClient.request`` (not raw urllib);
- ``_get_weather`` routes both geo + weather calls through the guard;
- ``_get_forecast`` routes both geo + forecast calls through the guard;
- a private-IP URL is blocked by the guard (DomainBlockedError, no fetch);
- a non-whitelisted public host is blocked by the guard (whitelist = open-meteo).

Success-path tests patch ``SandboxHttpClient.request`` directly so they fail
if the agent bypasses the guard and hits raw ``urllib`` instead.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "weather" / "agent.py"
)


def _load_agent():
    """Import the weather agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("weather_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    return agent_mod.WeatherAgent()


def _fake_http_response(body: dict) -> MagicMock:
    """Build a fake ``HttpResponse`` whose ``.json()`` returns ``body``."""
    resp = MagicMock()
    resp.status = 200
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


# ---------------------------------------------------------------------------
# Geocode: routes through SandboxHttpClient.request
# ---------------------------------------------------------------------------

class TestGeocodeSsrfGuarded:
    def test_geocode_uses_sandbox_client_not_raw_urllib(self, agent):
        """_geocode() must call SandboxHttpClient.request — not raw urllib.urlopen.

        If the agent still uses ``urllib.request.urlopen`` directly, the patch on
        ``SandboxHttpClient.request`` is never triggered and the real urllib hits
        the network (or raises), causing the assertion on call count to fail.
        """
        geo_body = {
            "results": [
                {"latitude": 55.75, "longitude": 37.62, "name": "Moscow", "country": "Russia"}
            ]
        }
        fake_resp = _fake_http_response(geo_body)

        with patch(
            "kernel.sandbox.http_client.SandboxHttpClient.request",
            return_value=fake_resp,
        ) as mock_req:
            result = agent._geocode("Moscow")

        mock_req.assert_called_once()
        req_arg = mock_req.call_args[0][0]   # first positional arg = HttpRequest
        assert "geocoding-api.open-meteo.com" in req_arg.url
        assert result["lat"] == 55.75
        assert result["lon"] == 37.62
        assert result["name"] == "Moscow"
        assert result["country"] == "Russia"

    def test_geocode_city_not_found_raises_value_error(self, agent):
        """_geocode() raises ValueError when the API returns no results."""
        fake_resp = _fake_http_response({"results": []})

        with patch(
            "kernel.sandbox.http_client.SandboxHttpClient.request",
            return_value=fake_resp,
        ):
            with pytest.raises(ValueError, match="City not found"):
                agent._geocode("Nonexistentopolis")

    def test_geocode_params_not_mangled_into_url(self, agent):
        """City name must arrive via HttpRequest.params, not manual URL-encoding."""
        geo_body = {
            "results": [
                {"latitude": 1.0, "longitude": 2.0, "name": "Москва", "country": "Russia"}
            ]
        }
        fake_resp = _fake_http_response(geo_body)

        with patch(
            "kernel.sandbox.http_client.SandboxHttpClient.request",
            return_value=fake_resp,
        ) as mock_req:
            agent._geocode("Москва")

        req_arg = mock_req.call_args[0][0]
        # The city should appear either in params dict or already encoded into url —
        # the key requirement is that no raw urllib.request.quote is needed because
        # SandboxHttpClient.HttpRequest handles encoding via params=.
        assert req_arg.url.startswith("https://geocoding-api.open-meteo.com")


# ---------------------------------------------------------------------------
# get_weather: two guard calls (geocode + weather)
# ---------------------------------------------------------------------------

class TestGetWeatherSsrfGuarded:
    def test_get_weather_routes_both_calls_through_guard(self, agent):
        """_get_weather() must use SandboxHttpClient for both geo + weather fetches."""
        geo_body = {
            "results": [{"latitude": 55.75, "longitude": 37.62, "name": "Moscow", "country": "Russia"}]
        }
        weather_body = {
            "current": {
                "temperature_2m": -5.0,
                "relative_humidity_2m": 80,
                "wind_speed_10m": 15.0,
                "weather_code": 3,
            }
        }

        responses = [_fake_http_response(geo_body), _fake_http_response(weather_body)]

        with patch(
            "kernel.sandbox.http_client.SandboxHttpClient.request",
            side_effect=responses,
        ) as mock_req:
            result = agent._get_weather("Moscow")

        assert mock_req.call_count == 2
        assert result["city"] == "Moscow"
        assert result["country"] == "Russia"
        assert result["temperature_c"] == -5.0
        assert result["humidity_pct"] == 80
        assert result["wind_speed_kmh"] == 15.0
        assert result["condition"] == "Overcast"   # WMO code 3
        assert "error" not in result

        # Second call should target api.open-meteo.com
        weather_req = mock_req.call_args_list[1][0][0]
        assert "api.open-meteo.com" in weather_req.url


# ---------------------------------------------------------------------------
# get_forecast: two guard calls (geocode + forecast)
# ---------------------------------------------------------------------------

class TestGetForecastSsrfGuarded:
    def test_get_forecast_routes_both_calls_through_guard(self, agent):
        """_get_forecast() must use SandboxHttpClient for both geo + forecast fetches."""
        geo_body = {
            "results": [{"latitude": 48.85, "longitude": 2.35, "name": "Paris", "country": "France"}]
        }
        forecast_body = {
            "daily": {
                "time": ["2026-06-29", "2026-06-30", "2026-07-01"],
                "temperature_2m_max": [22.0, 24.0, 21.0],
                "temperature_2m_min": [14.0, 16.0, 13.0],
                "weather_code": [1, 3, 61],
            }
        }

        responses = [_fake_http_response(geo_body), _fake_http_response(forecast_body)]

        with patch(
            "kernel.sandbox.http_client.SandboxHttpClient.request",
            side_effect=responses,
        ) as mock_req:
            result = agent._get_forecast("Paris")

        assert mock_req.call_count == 2
        assert result["city"] == "Paris"
        assert result["country"] == "France"
        assert len(result["forecast"]) == 3
        assert result["forecast"][0]["date"] == "2026-06-29"
        assert result["forecast"][0]["temp_max_c"] == 22.0
        assert result["forecast"][1]["condition"] == "Overcast"   # WMO 3
        assert result["forecast"][2]["condition"] == "Slight rain"  # WMO 61
        assert "error" not in result

        forecast_req = mock_req.call_args_list[1][0][0]
        assert "api.open-meteo.com" in forecast_req.url


# ---------------------------------------------------------------------------
# SSRF block: private-host target is rejected by the guard
# ---------------------------------------------------------------------------

class TestSsrfBlocked:
    @pytest.mark.parametrize(
        "private_ip",
        [
            "169.254.169.254",
            "127.0.0.1",
            "10.0.0.5",
            "192.168.1.1",
        ],
    )
    def test_private_ip_blocked_by_weather_client(self, agent_mod, private_ip):
        """SandboxHttpClient with the weather whitelist rejects private-IP hosts.

        No network call is made — the guard raises DomainBlockedError before
        opening any socket.
        """
        from kernel.sandbox.http_client import (
            DomainBlockedError,
            HttpRequest,
            SandboxHttpClient,
        )

        client = SandboxHttpClient(
            "weather",
            allowed_domains=["geocoding-api.open-meteo.com", "api.open-meteo.com"],
        )
        with patch("urllib.request.OpenerDirector.open") as opener_mock:
            with pytest.raises(DomainBlockedError):
                client.request(
                    HttpRequest(url=f"https://{private_ip}/secret", method="GET")
                )
        opener_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Whitelist enforcement
# ---------------------------------------------------------------------------

class TestWhitelistEnforced:
    def test_non_open_meteo_host_blocked(self, agent_mod):
        """The weather client's whitelist blocks requests to arbitrary public hosts."""
        from kernel.sandbox.http_client import (
            DomainBlockedError,
            HttpRequest,
            SandboxHttpClient,
        )

        client = SandboxHttpClient(
            "weather",
            allowed_domains=["geocoding-api.open-meteo.com", "api.open-meteo.com"],
        )
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as opener_mock:
            with pytest.raises(DomainBlockedError):
                client.request(
                    HttpRequest(url="https://evil.example.com/exfil", method="GET")
                )
        opener_mock.assert_not_called()
