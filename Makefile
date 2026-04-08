.PHONY: dev test lint format install build kernel-dev ui-dev

install:
	uv sync --all-extras
	cd ui && pnpm install

kernel-dev:
	uv run uvicorn kernel.main:create_app --factory --reload --port 8000

ui-dev:
	cd ui && pnpm dev

dev:
	@echo "Starting Jarvis (kernel + UI)..."
	@make kernel-dev &
	@sleep 2
	@make ui-dev

test:
	uv run pytest -v

lint:
	uv run ruff check kernel/ tests/ agents/
	cd ui && npx tsc --noEmit

format:
	uv run ruff format kernel/ tests/ agents/
	uv run ruff check --fix kernel/ tests/ agents/

build:
	cd ui && pnpm build
