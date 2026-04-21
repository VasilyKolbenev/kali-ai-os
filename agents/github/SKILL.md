---
name: github
description: GitHub integration — repos, issues, and pull requests Use when user mentions
  my_repos, my_issues, my_prs.
compatibility: requires network access
metadata:
  migrated_from: legacy_manifest_v1
  original_version: 1.0.0
allowed-tools: my_repos my_issues my_prs repo_status
---

# github

## Capabilities
- github.repos
- github.issues
- github.prs

## Actions
- **my_repos** — List the authenticated user's repositories (sorted by last update)
- **my_issues** — List issues assigned to the authenticated user
- **my_prs** — List open pull requests authored by the authenticated user
- **repo_status** — Get detailed info about a specific repository

## Implementation

This skill wraps a legacy `agent.py` script. The runtime calls 
`CustomAgent.handle_action(action, args)` in-process.

See `scripts/agent.py` for the implementation.
