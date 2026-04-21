---
name: tasks
description: Task and todo management Use when user mentions add_task, list_tasks,
  complete_task.
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: add_task list_tasks complete_task delete_task get_summary
---

# tasks

## Capabilities
- tasks.read
- tasks.write

## Actions
- **add_task** — Add a new task
- **list_tasks** — List all tasks
- **complete_task** — Mark a task as complete
- **delete_task** — Delete a task
- **get_summary** — Get task summary (total, done, pending)

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
