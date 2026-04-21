---
name: telegram
description: Telegram bot - remote control and notifications Use when user mentions
  send_message, send_notification, get_status.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: send_message send_notification get_status
---

# telegram

## Capabilities
- telegram.send
- telegram.notify

## Actions
- **send_message** — Send a message via Telegram
- **send_notification** — Send a formatted notification via Telegram
- **get_status** — Get Telegram bot connection status

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
