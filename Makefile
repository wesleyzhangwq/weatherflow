.PHONY: install lint format-check test check dev clean

PY := uv run --package weatherflow-core --extra dev

install:
	uv sync --all-packages --all-extras

lint:
	$(PY) ruff check core/src core/tests

format-check:
	$(PY) ruff format --check core/src core/tests

test:
	$(PY) pytest core/tests -q

check: lint format-check test

dev:
	uv run --package weatherflow-core weatherflow serve --reload

clean:
	find core -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find core -type f -name '*.pyc' -delete
