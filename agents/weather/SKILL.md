---
name: weather
description: Weather information via Open-Meteo API Use when user mentions get_weather,
  get_forecast.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: get_weather get_forecast
---

# weather

## Capabilities
- weather.current
- weather.forecast

## Actions
- **get_weather** — Get current weather for a location
- **get_forecast** — Get weather forecast for next 3 days

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
