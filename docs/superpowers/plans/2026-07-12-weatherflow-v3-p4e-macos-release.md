# WeatherFlow v3 P4e macOS Release Plan

**Goal:** Produce and verify a self-contained unsigned arm64 macOS release, then sign/notarize only when valid user-held Apple credentials already exist.

## P4e1: Standalone daemon and supervision

- [ ] Add a reproducible PyInstaller sidecar build with pinned workspace dependencies and no shell shim fallback.
- [ ] Verify the standalone daemon serves authenticated health and Run APIs without Python or project paths in its runtime environment.
- [ ] Verify Tauri starts, monitors, and stops the binary under the existing bounded supervisor.

## P4e2: Bundle metadata and release assets

- [ ] Add production icons, Info.plist metadata, hardened-runtime entitlements, minimum macOS version, category, copyright, and deep-link metadata where applicable.
- [ ] Add release scripts that build arm64 `.app` and `.dmg`, preserve logs, and never silently skip a failed stage.
- [ ] Generate SHA-256 checksums plus a dependency/SBOM and license inventory for Python, Node, and Rust inputs.

## P4e3: Unsigned validation and credential boundary

- [ ] Inspect bundle structure, architectures, sidecar executability, forbidden absolute paths, bridge authentication, and quarantine/signature state.
- [ ] Smoke-launch the unsigned `.app`, confirm daemon health and UI process startup, then terminate cleanly.
- [ ] Detect Apple signing/notarization credentials without printing secrets. Sign/notarize only when complete credentials are present; otherwise record the exact credential-only blocker.

## P4e4: Final release audit

- [ ] Run `make check`, standalone-sidecar tests, release artifact checks, security scan, and checksum verification.
- [ ] Audit P0-P4 against architecture, privacy, authority, recovery, and distribution contracts.
- [ ] Update release documentation and commit `release: harden WeatherFlow v3.0` without pushing or publishing.
