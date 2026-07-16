#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "run_signed_binary.sh requires the executable path" >&2
  exit 64
fi

SOURCE_BINARY="$1"
shift
IDENTITY="${WF_DEV_SIGNING_IDENTITY:-WeatherFlow Dev Signer}"
IDENTIFIER="${WF_DEV_BUNDLE_IDENTIFIER:-ai.weatherflow.desktop.dev}"
SOURCE_BINARY="$(cd "$(dirname "$SOURCE_BINARY")" && pwd -P)/$(basename "$SOURCE_BINARY")"
TARGET_ROOT="$(dirname "$(dirname "$SOURCE_BINARY")")"
SIGNED_CACHE="$TARGET_ROOT/weatherflow-dev-signed/weatherflow-desktop"
SOURCE_HASH_FILE="$TARGET_ROOT/weatherflow-dev-signed/source.sha256"

# `tauri dev` launches Cargo's raw debug executable instead of a bundled app.
# Cargo can restore its unsigned artifact before every `cargo run`, so signing
# that artifact in place still invokes Keychain on every wake. Keep a stable
# signed runtime copy and replace it only when the linked source bytes change.
existing_signature_is_usable() {
  local binary="$1"
  local details
  details=$(/usr/bin/codesign -d --verbose=4 "$binary" 2>&1) || return 1
  printf '%s\n' "$details" | grep -Fq "Identifier=$IDENTIFIER" || return 1
  printf '%s\n' "$details" | grep -Fq "Authority=$IDENTITY" || return 1
  /usr/bin/codesign --verify --strict "$binary" >/dev/null 2>&1
}

SOURCE_HASH=$(/usr/bin/shasum -a 256 "$SOURCE_BINARY" | awk '{print $1}')
CACHED_HASH=""
if [[ -f "$SOURCE_HASH_FILE" ]]; then
  CACHED_HASH=$(<"$SOURCE_HASH_FILE")
fi

if [[ "$SOURCE_HASH" == "$CACHED_HASH" ]] && existing_signature_is_usable "$SIGNED_CACHE"; then
  echo "[weatherflow-dev] reusing stable signed runtime: $IDENTITY"
else
  mkdir -p "$(dirname "$SIGNED_CACHE")"
  TEMP_BINARY="$SIGNED_CACHE.tmp.$$"
  cp "$SOURCE_BINARY" "$TEMP_BINARY"
  /usr/bin/codesign \
    --force \
    --sign "$IDENTITY" \
    --identifier "$IDENTIFIER" \
    --timestamp=none \
    "$TEMP_BINARY"
  mv -f "$TEMP_BINARY" "$SIGNED_CACHE"
  printf '%s\n' "$SOURCE_HASH" > "$SOURCE_HASH_FILE"
fi
/usr/bin/codesign --verify --strict --verbose=2 "$SIGNED_CACHE"

exec "$SIGNED_CACHE" "$@"
