test:
	uv run pytest tests/unit tests/integration -v

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

ui:
	uv run python -m src.webapp.app