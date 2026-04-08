"""Tests for Weather agent."""

import json
import os
import sys
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


def _make_mock_response(body: bytes) -> MagicMock:
    """Build a mock urlopen context manager returning body."""
    mock = MagicMock()
    mock.read.return_value = body
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


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
            _make_mock_response(GEOCODING_RESPONSE),
            _make_mock_response(CURRENT_WEATHER_RESPONSE),
        ]
        with patch("urllib.request.urlopen", side_effect=responses):
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
            _make_mock_response(GEOCODING_RESPONSE),
            _make_mock_response(FORECAST_RESPONSE),
        ]
        with patch("urllib.request.urlopen", side_effect=responses):
            result = agent.handle_action("get_forecast", {"city": "Moscow"})

        assert result["city"] == "Moscow"
        assert len(result["forecast"]) == 3
        assert result["forecast"][0]["date"] == "2026-04-08"
        assert result["forecast"][0]["temp_max_c"] == 8.0
        assert result["forecast"][0]["condition"] == "Mainly clear"

    def test_city_not_found_raises_value_error(self) -> None:
        agent = WeatherAgent()
        empty_response = _make_mock_response(json.dumps({"results": []}).encode())
        with patch("urllib.request.urlopen", return_value=empty_response):
            with pytest.raises(ValueError, match="City not found"):
                agent.handle_action("get_weather", {"city": "InvalidXYZ"})

    def test_get_weather_network_error_returns_error_dict(self) -> None:
        agent = WeatherAgent()

        def boom(url, timeout=10):  # type: ignore[no-untyped-def]
            raise OSError("connection refused")

        geo_response = _make_mock_response(GEOCODING_RESPONSE)
        with patch("urllib.request.urlopen", side_effect=[geo_response, OSError("network err")]):
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
            _make_mock_response(GEOCODING_RESPONSE),
            _make_mock_response(forecast_with_unknown_code),
        ]
        with patch("urllib.request.urlopen", side_effect=responses):
            result = agent.handle_action("get_forecast", {"city": "Moscow"})

        assert result["forecast"][0]["condition"] == "Unknown"
