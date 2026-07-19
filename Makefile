.PHONY: install lint format-check test eval security-check desktop-check rust-check check sidecar-check release-app run-release release-check dev clean

PY := uv run --package weatherflow-core --extra dev
RELEASE_APP := $(abspath release/macos/WeatherFlow.app)

install:
	uv sync --all-packages --all-extras
	pnpm install --frozen-lockfile

lint:
	$(PY) ruff check core/src core/tests

format-check:
	$(PY) ruff format --check core/src core/tests

test:
	$(PY) pytest core/tests -q --ignore=core/tests/eval --ignore=core/tests/operations/test_hardening.py

eval:
	$(PY) pytest core/tests/eval -q

security-check:
	$(PY) pytest core/tests/operations/test_hardening.py -q

desktop-check:
	pnpm --filter weatherflow-desktop lint
	pnpm --filter weatherflow-desktop typecheck
	pnpm --filter weatherflow-desktop test
	pnpm --filter weatherflow-desktop build

rust-check:
	cd desktop/src-tauri && TOOLCHAIN_BIN=$$(dirname "$$(rustup which cargo)") && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo fmt --check && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo test --lib && PATH="$$TOOLCHAIN_BIN:$$PATH" cargo check

check: lint format-check test eval security-check desktop-check rust-check

sidecar-check:
	python3 tools/release/test_sidecar.py desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin
	python3 tools/release/test_desktop_sidecar.py desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin

release-app:
	python3 tools/release/release_macos.py

run-release: release-app
	test -d "$(RELEASE_APP)"
	test -f "$(RELEASE_APP)/Contents/Info.plist"
	test -d "$(RELEASE_APP)/Contents/MacOS"
	codesign --verify --deep --strict --verbose=2 "$(RELEASE_APP)"
	python3 tools/release/run_release.py

release-check: check sidecar-check
	cd release/macos && shasum -a 256 -c CHECKSUMS.sha256
	codesign --verify --deep --strict --verbose=2 release/macos/WeatherFlow.app
	hdiutil verify release/macos/WeatherFlow_3.0.0-alpha.1_aarch64.dmg

dev:
	uv run --package weatherflow-core weatherflow serve --reload

clean:
	rm -rf core/build desktop/dist desktop/src-tauri/target release/pyinstaller desktop/node_modules/.tmp desktop/node_modules/.vite .pytest_cache .ruff_cache
	find core tools desktop/src-tauri -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find core tools desktop/src-tauri -type f -name '*.pyc' -delete
	find . -path './.git' -prune -o -name '.DS_Store' -type f -delete
