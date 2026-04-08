.PHONY: dev test lint format install

install:
	uv sync --all-extras

dev:
	uv run uvicorn kernel.main:create_app --factory --reload --port 8000

test:
	uv run pytest -v

lint:
	uv run ruff check kernel/ tests/
	uv run mypy kernel/

format:
	uv run ruff format kernel/ tests/
	uv run ruff check --fix kernel/ tests/
