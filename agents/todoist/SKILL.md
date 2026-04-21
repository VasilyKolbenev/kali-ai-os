---
name: todoist
description: Todoist task management — list, add, and complete tasks Use when user
  mentions get_tasks, add_task, complete_task.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: get_tasks add_task complete_task
---

# todoist

## Capabilities
- todoist.read
- todoist.write

## Actions
- **get_tasks** — List all active Todoist tasks
- **add_task** — Create a new Todoist task
- **complete_task** — Mark a Todoist task as completed

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
