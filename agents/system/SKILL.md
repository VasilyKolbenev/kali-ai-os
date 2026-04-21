---
name: system
description: System commands - time, timers, system info Use when user mentions get_time,
  get_system_info, set_timer.
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: get_time get_system_info set_timer
---

# system

## Capabilities
- system.info
- system.timer

## Actions
- **get_time** — Get current date and time
- **get_system_info** — Get system information (OS, CPU, memory)
- **set_timer** — Set a countdown timer

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
