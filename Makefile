.PHONY: install lint format-check test eval security-check desktop-check rust-check check sidecar-check release-check dev clean

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

security-check:
	$(PY) pytest core/tests/operations/test_hardening.py -q

desktop-check:
	cd desktop && npm run lint && npm run typecheck && npm test && npm run build

rust-check:
	cd desktop/src-tauri && TOOLCHAIN_BIN=$$(dirname "$$(rustup which cargo)") && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo fmt --check && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo test --lib && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo check

check: lint format-check test eval security-check desktop-check rust-check

sidecar-check:
	python3 tools/release/test_sidecar.py desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin

release-check: check sidecar-check
	cd release/macos && shasum -a 256 -c CHECKSUMS.sha256
	codesign --verify --deep --strict --verbose=2 release/macos/WeatherFlow.app
	hdiutil verify release/macos/WeatherFlow_3.0.0-alpha.1_aarch64.dmg

dev:
	uv run --package weatherflow-core weatherflow serve --reload

clean:
	find core -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find core -type f -name '*.pyc' -delete
