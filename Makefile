.PHONY: dev test test-core-loop lint format install build kernel-dev ui-dev install-hooks

install:
	uv sync --all-extras
	cd ui && pnpm install

kernel-dev:
	uv run uvicorn kernel.main:create_app --factory --reload --port 3005

ui-dev:
	cd ui && pnpm dev

dev:
	@echo "Starting KALI (kernel + UI)..."
	@make kernel-dev &
	@sleep 2
	@make ui-dev

test:
	uv run pytest -v

# Fast, ML-free gate for the "create → works → share" core loop (~5s, no torch/F5/whisper).
# Re-verifies the voice build→deploy→schedule→dispatch→share path on every change.
# Uses the venv python directly so it runs without `uv run` (e.g. from the pre-push hook).
test-core-loop:
	.venv/Scripts/python.exe -m pytest -m core_loop -q

# Opt-in: route git hooks to scripts/git-hooks so `git push` runs the core-loop gate.
# Explicit (won't clobber your existing .git/hooks); undo with `git config --unset core.hooksPath`.
install-hooks:
	git config core.hooksPath scripts/git-hooks
	@echo "core.hooksPath -> scripts/git-hooks (pre-push now runs 'make test-core-loop')"

lint:
	uv run ruff check kernel/ tests/ agents/
	cd ui && npx tsc --noEmit

format:
	uv run ruff format kernel/ tests/ agents/
	uv run ruff check --fix kernel/ tests/ agents/

build:
	cd ui && pnpm build
