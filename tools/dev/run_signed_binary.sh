#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "run_signed_binary.sh requires the executable path" >&2
  exit 64
fi

BINARY="$1"
shift
IDENTITY="${WF_DEV_SIGNING_IDENTITY:-WeatherFlow Dev Signer}"
IDENTIFIER="${WF_DEV_BUNDLE_IDENTIFIER:-ai.weatherflow.desktop.dev}"

# `tauri dev` launches Cargo's raw debug executable instead of a bundled app.
# Sign that final artifact after linking and before its first instruction runs.
# A fixed certificate plus identifier gives Keychain/TCC a stable designated
# requirement across rebuilds; an ad-hoc signature would fall back to CDHash.
/usr/bin/codesign \
  --force \
  --sign "$IDENTITY" \
  --identifier "$IDENTIFIER" \
  --timestamp=none \
  "$BINARY"
/usr/bin/codesign --verify --strict --verbose=2 "$BINARY"

exec "$BINARY" "$@"
