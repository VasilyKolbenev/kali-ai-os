---
name: currency
description: Exchange rates and currency conversion via open.er-api.com (free, no
  key required) Use when user mentions get_rates, convert.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: get_rates convert
---

# currency

## Capabilities
- currency.rates
- currency.convert

## Actions
- **get_rates** — Get current exchange rates for a base currency
- **convert** — Convert an amount from one currency to another

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
