---
name: news
description: News headlines and search via NewsAPI Use when user mentions top_headlines,
  search.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: top_headlines search
---

# news

## Capabilities
- news.headlines
- news.search

## Actions
- **top_headlines** — Fetch top news headlines
- **search** — Search news articles by query

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
