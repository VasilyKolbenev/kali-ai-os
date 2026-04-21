---
name: coding
description: Coding assistant - code review, generation, explanation Use when user
  mentions explain_code, review_code, suggest_improvement.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: explain_code review_code suggest_improvement
---

# coding

## Capabilities
- coding.review
- coding.generate
- coding.explain

## Actions
- **explain_code** — Explain what a piece of code does
- **review_code** — Review code for issues
- **suggest_improvement** — Suggest improvements for code

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
