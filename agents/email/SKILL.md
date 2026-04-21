---
name: email
description: Email management via Gmail API Use when user mentions check_inbox, send_email,
  search_emails.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: check_inbox send_email search_emails
---

# email

## Capabilities
- email.read
- email.send
- email.search

## Actions
- **check_inbox** — Check recent emails
- **send_email** — Send an email
- **search_emails** — Search emails by query

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
