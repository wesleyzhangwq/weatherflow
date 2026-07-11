.PHONY: install lint format-check test eval desktop-check rust-check check dev clean

PY := uv run --package weatherflow-core --extra dev

install:
	uv sync --all-packages --all-extras
	cd desktop && npm ci

lint:
	$(PY) ruff check core/src core/tests

format-check:
	$(PY) ruff format --check core/src core/tests

test:
	$(PY) pytest core/tests -q --ignore=core/tests/eval

eval:
	$(PY) pytest core/tests/eval -q

desktop-check:
	cd desktop && npm run lint && npm run typecheck && npm test && npm run build

rust-check:
	cd desktop/src-tauri && TOOLCHAIN_BIN=$$(dirname "$$(rustup which cargo)") && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo fmt --check && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo test --lib && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo check

check: lint format-check test eval desktop-check rust-check

dev:
	uv run --package weatherflow-core weatherflow serve --reload

clean:
	find core -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find core -type f -name '*.pyc' -delete
