"""Domain routers extracted from kernel/main.py (2026-07-13 split).

Each module exposes ``router: APIRouter``; ``create_app()`` includes them in
the original registration order (intra-module def order is load-bearing —
/skills/{name}/{action} shadows /skills/catalog/refresh by design; see
docs/superpowers/plans/2026-07-13-mainpy-split.md).
"""
