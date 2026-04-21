---
name: smart-home
description: Home automation via Home Assistant Use when user mentions get_devices,
  control_device, get_status.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: get_devices control_device get_status
---

# smart-home

## Capabilities
- smarthome.lights
- smarthome.climate
- smarthome.devices

## Actions
- **get_devices** — List smart home devices
- **control_device** — Control a smart home device
- **get_status** — Get status of all devices

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
