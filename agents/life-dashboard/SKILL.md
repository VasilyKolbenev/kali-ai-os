---
name: life-dashboard
description: Life tracking - sleep, spending, energy, habits Use when user mentions
  log_sleep, log_spending, log_energy.
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: log_sleep log_spending log_energy get_daily_summary
---

# life-dashboard

## Capabilities
- dashboard.read
- dashboard.write

## Actions
- **log_sleep** — Log sleep data
- **log_spending** — Log a spending entry
- **log_energy** — Log calorie intake
- **get_daily_summary** — Get today's life dashboard summary

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
