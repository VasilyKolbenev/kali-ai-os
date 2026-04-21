---
name: notion
description: Notion workspace integration — search, read, and create pages Use when
  user mentions search, get_page, create_page.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: search get_page create_page
---

# notion

## Capabilities
- notion.search
- notion.read
- notion.write

## Actions
- **search** — Search Notion pages and databases
- **get_page** — Get a Notion page by ID
- **create_page** — Create a new page in a Notion database

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
