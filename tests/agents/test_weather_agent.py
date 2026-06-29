"""Tests for Weather agent."""

import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from agents.weather.agent import WeatherAgent

GEOCODING_RESPONSE = json.dumps(
    {
        "results": [
            {
                "name": "Moscow",
                "latitude": 55.75,
                "longitude": 37.62,
                "country": "Russia",
            }
        ]
    }
).encode()

CURRENT_WEATHER_RESPONSE = json.dumps(
    {
        "current": {
            "temperature_2m": 5.0,
            "relative_humidity_2m": 80,
            "wind_speed_10m": 12.0,
            "weather_code": 3,
        }
    }
).encode()

FORECAST_RESPONSE = json.dumps(
    {
        "daily": {
            "time": ["2026-04-08", "2026-04-09", "2026-04-10"],
            "temperature_2m_max": [8.0, 10.0, 7.0],
            "temperature_2m_min": [2.0, 3.0, 1.0],
            "weather_code": [1, 63, 71],
        }
    }
).encode()


def _make_mock_response(body: bytes, url: str = "https://api.open-meteo.com/v1/forecast") -> MagicMock:
    """Build a guard-compatible mock for ``OpenerDirector.open``.

    Mirrors ``test_github_ssrf.py._mock_opener_open``: exposes ``.status``,
    ``.url``, ``.headers.items()``, ``.read()``, and context-manager protocol
    so the guard's ``with opener.open(...) as resp`` block works correctly.
    """
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = url
    mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestWeatherAgent:
    def test_get_name(self) -> None:
        agent = WeatherAgent()
        assert agent.get_name() == "weather"

    def test_unknown_action_raises(self) -> None:
        agent = WeatherAgent()
        with pytest.raises(ValueError, match="Unknown action"):
            agent.handle_action("nonexistent", {})

    def test_get_weather_returns_current(self) -> None:
        agent = WeatherAgent()
        responses = [
            _make_mock_response(GEOCODING_RESPONSE, "https://geocoding-api.open-meteo.com/v1/search"),
            _make_mock_response(CURRENT_WEATHER_RESPONSE, "https://api.open-meteo.com/v1/forecast"),
        ]
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", side_effect=responses
        ):
            result = agent.handle_action("get_weather", {"city": "Moscow"})

        assert result["city"] == "Moscow"
        assert result["country"] == "Russia"
        assert result["temperature_c"] == 5.0
        assert result["humidity_pct"] == 80
        assert result["wind_speed_kmh"] == 12.0
        assert result["condition"] == "Overcast"
        assert result["weather_code"] == 3

    def test_get_forecast_returns_three_days(self) -> None:
        agent = WeatherAgent()
        responses = [
            _make_mock_response(GEOCODING_RESPONSE, "https://geocoding-api.open-meteo.com/v1/search"),
            _make_mock_response(FORECAST_RESPONSE, "https://api.open-meteo.com/v1/forecast"),
        ]
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", side_effect=responses
        ):
            result = agent.handle_action("get_forecast", {"city": "Moscow"})

        assert result["city"] == "Moscow"
        assert len(result["forecast"]) == 3
        assert result["forecast"][0]["date"] == "2026-04-08"
        assert result["forecast"][0]["temp_max_c"] == 8.0
        assert result["forecast"][0]["condition"] == "Mainly clear"

    def test_city_not_found_raises_value_error(self) -> None:
        agent = WeatherAgent()
        empty_resp = _make_mock_response(
            json.dumps({"results": []}).encode(),
            "https://geocoding-api.open-meteo.com/v1/search",
        )
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", return_value=empty_resp
        ):
            with pytest.raises(ValueError, match="City not found"):
                agent.handle_action("get_weather", {"city": "InvalidXYZ"})

    def test_get_weather_network_error_returns_error_dict(self) -> None:
        agent = WeatherAgent()
        geo_response = _make_mock_response(
            GEOCODING_RESPONSE,
            "https://geocoding-api.open-meteo.com/v1/search",
        )
        # The guard catches URLError and re-raises SandboxHttpError, which the
        # agent's except-Exception clause catches → error dict returned.
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open",
            side_effect=[geo_response, urllib.error.URLError("network err")],
        ):
            result = agent.handle_action("get_weather", {"city": "Moscow"})

        assert "error" in result

    def test_forecast_unknown_wmo_code_returns_unknown(self) -> None:
        agent = WeatherAgent()
        forecast_with_unknown_code = json.dumps(
            {
                "daily": {
                    "time": ["2026-04-08"],
                    "temperature_2m_max": [10.0],
                    "temperature_2m_min": [5.0],
                    "weather_code": [999],
                }
            }
        ).encode()
        responses = [
            _make_mock_response(GEOCODING_RESPONSE, "https://geocoding-api.open-meteo.com/v1/search"),
            _make_mock_response(forecast_with_unknown_code, "https://api.open-meteo.com/v1/forecast"),
        ]
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", side_effect=responses
        ):
            result = agent.handle_action("get_forecast", {"city": "Moscow"})

        assert result["forecast"][0]["condition"] == "Unknown"
