# WeatherFlow v3.0 macOS release checklist

## Reproduce

1. Use arm64 macOS 13 or newer with Xcode command-line tools, Node, `uv`, and
   the Rust toolchain available through `rustup`.
2. Run `uv sync --all-packages --all-extras` and `npm ci` in `desktop/`.
3. Run `python3 tools/release/release_macos.py` from the repository root.
4. Run `make release-check`.

The release script rebuilds the standalone Python daemon, verifies it in a
minimal environment, builds the Tauri application, smoke-launches the app and
supervised sidecar, creates a non-interactive arm64 DMG, generates dependency
and license inventories, and writes checksums.

## Required inspection

- `WeatherFlow.app` and both executables are arm64.
- The bundle identifier is `ai.weatherflow.desktop`; minimum macOS is 13.0.
- The sidecar is an executable Mach-O, not a shell launcher.
- No repository/build absolute path occurs in either executable.
- The app launches a child `weatherflow-core` and terminates cleanly.
- `codesign --verify --deep --strict` passes for the ad-hoc local bundle.
- `hdiutil verify` and every entry in `CHECKSUMS.sha256` pass.
- `release-status.json` truthfully distinguishes ad-hoc, signed, and notarized
  artifacts.

## Signing boundary

For distributable signing, install a `Developer ID Application` identity and
provide `APPLE_ID`, `APPLE_PASSWORD` (app-specific), and `APPLE_TEAM_ID` in the
release environment. The script signs with hardened runtime, submits through
`notarytool`, waits for acceptance, and staples the DMG. It never prints those
values. Without the complete credential set, it creates a verified ad-hoc
bundle and records the credential-only blocker in `SIGNING_BLOCKER.md`.

Release output is local at `release/macos/`. Large `.app` and `.dmg` products
are reproducible and git-ignored; their checksum, SBOM, license inventory,
status, and blocker records are tracked.
