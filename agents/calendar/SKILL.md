---
name: calendar
description: Calendar and scheduling Use when user mentions get_events, create_event,
  delete_event.
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: get_events create_event delete_event
---

# calendar

## Capabilities
- calendar.read
- calendar.write

## Actions
- **get_events** — Get calendar events for a date
- **create_event** — Create a new calendar event
- **delete_event** — Delete a calendar event

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
