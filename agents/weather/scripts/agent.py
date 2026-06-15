"""Weather agent — current weather and forecast via Open-Meteo API (free, no key)."""

import json
import os
import sys
import urllib.request
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
}


class WeatherAgent(BaseAgent):
    """Agent for fetching current weather and forecasts via Open-Meteo."""

    def get_name(self) -> str:
        """Return agent name."""
        return "weather"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (get_weather, get_forecast).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        if action == "get_weather":
            return self._get_weather(args.get("city", "Moscow"))
        elif action == "get_forecast":
            return self._get_forecast(args.get("city", "Moscow"))
        else:
            raise ValueError(f"Unknown action: {action}")

    def _geocode(self, city: str) -> dict[str, Any]:
        """Get coordinates for a city name.

        Args:
            city: City name to geocode.

        Returns:
            Dict with lat, lon, name, country.

        Raises:
            ValueError: If city not found.
        """
        # language=ru resolves BOTH Cyrillic ("Москва") and Latin ("Moscow")
        # city names; language=en silently fails on Cyrillic, which is exactly
        # what voice STT produces for a Russian speaker.
        url = f"{GEOCODING_URL}?name={urllib.request.quote(city)}&count=1&language=ru"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", [])
        if not results:
            raise ValueError(f"City not found: {city}")
        return {
            "lat": results[0]["latitude"],
            "lon": results[0]["longitude"],
            "name": results[0]["name"],
            "country": results[0].get("country", ""),
        }

    def _get_weather(self, city: str) -> dict[str, Any]:
        """Get current weather for a city.

        Args:
            city: City name.

        Returns:
            Dict with temperature, humidity, wind speed, condition.
        """
        try:
            geo = self._geocode(city)
            url = (
                f"{WEATHER_URL}?latitude={geo['lat']}&longitude={geo['lon']}"
                f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
                f"&timezone=auto"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            current = data.get("current", {})
            code = current.get("weather_code", 0)
            return {
                "city": geo["name"],
                "country": geo["country"],
                "temperature_c": current.get("temperature_2m"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "condition": WMO_CODES.get(code, "Unknown"),
                "weather_code": code,
            }
        except ValueError:
            raise
        except Exception as e:
            return {"error": str(e), "city": city}

    def _get_forecast(self, city: str) -> dict[str, Any]:
        """Get 3-day forecast for a city.

        Args:
            city: City name.

        Returns:
            Dict with city, country, and list of forecast days.
        """
        try:
            geo = self._geocode(city)
            url = (
                f"{WEATHER_URL}?latitude={geo['lat']}&longitude={geo['lon']}"
                f"&daily=temperature_2m_max,temperature_2m_min,weather_code"
                f"&forecast_days=3&timezone=auto"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            daily = data.get("daily", {})
            days = []
            for i in range(len(daily.get("time", []))):
                code = daily["weather_code"][i]
                days.append(
                    {
                        "date": daily["time"][i],
                        "temp_max_c": daily["temperature_2m_max"][i],
                        "temp_min_c": daily["temperature_2m_min"][i],
                        "condition": WMO_CODES.get(code, "Unknown"),
                    }
                )

            return {"city": geo["name"], "country": geo["country"], "forecast": days}
        except ValueError:
            raise
        except Exception as e:
            return {"error": str(e), "city": city}


if __name__ == "__main__":
    WeatherAgent().run()
