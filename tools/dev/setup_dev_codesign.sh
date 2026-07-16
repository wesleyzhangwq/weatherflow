#!/usr/bin/env bash
set -euo pipefail

IDENTITY="${WF_DEV_SIGNING_IDENTITY:-WeatherFlow Dev Signer}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
CERT_DIR=$(mktemp -d)
KEY="$CERT_DIR/weatherflow-dev.key"
CERT="$CERT_DIR/weatherflow-dev.crt"
P12="$CERT_DIR/weatherflow-dev.p12"
P12_PASS=$(openssl rand -hex 24)

cleanup() {
  rm -rf "$CERT_DIR"
}
trap cleanup EXIT

if security find-identity -v -p codesigning 2>/dev/null | grep -Fq "\"$IDENTITY\""; then
  echo "[weatherflow-dev] Local signing identity already exists: $IDENTITY"
  exit 0
fi

echo "[weatherflow-dev] Creating the local signing identity: $IDENTITY"
echo "[weatherflow-dev] macOS will request the login Keychain password once."

cat > "$CERT_DIR/openssl.conf" <<EOF
[ req ]
distinguished_name = subject
prompt = no
x509_extensions = code_signing

[ subject ]
CN = $IDENTITY

[ code_signing ]
basicConstraints = CA:FALSE
keyUsage = digitalSignature,nonRepudiation,keyEncipherment,dataEncipherment
extendedKeyUsage = codeSigning
EOF

openssl req \
  -newkey rsa:2048 \
  -nodes \
  -keyout "$KEY" \
  -x509 \
  -days 3650 \
  -out "$CERT" \
  -config "$CERT_DIR/openssl.conf" \
  2>/dev/null

PKCS12_LEGACY_ARGS=()
if openssl pkcs12 -help 2>&1 | grep -q -- '-legacy'; then
  PKCS12_LEGACY_ARGS=(-legacy)
fi
openssl pkcs12 \
  "${PKCS12_LEGACY_ARGS[@]}" \
  -export \
  -out "$P12" \
  -inkey "$KEY" \
  -in "$CERT" \
  -passout "pass:$P12_PASS"

security import "$P12" \
  -k "$KEYCHAIN" \
  -P "$P12_PASS" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

# Limit the partition-list update to the newly imported private signing key.
security set-key-partition-list \
  -S apple-tool:,apple:,codesign:,unsigned: \
  -l "$IDENTITY" \
  -t private \
  -s \
  "$KEYCHAIN"

security add-trusted-cert \
  -r trustRoot \
  -p basic \
  -p codeSign \
  -k "$KEYCHAIN" \
  "$CERT"

echo "[weatherflow-dev] Ready. Future pnpm dev:app rebuilds use: $IDENTITY"
