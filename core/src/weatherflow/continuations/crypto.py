import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from weatherflow.continuations.models import ProviderContinuationUnavailableError


@dataclass(frozen=True, slots=True)
class EncryptedContinuation:
    nonce: bytes
    ciphertext: bytes
    payload_sha256: str


class ContinuationCipher:
    """AES-256-GCM envelope with canonical authenticated metadata."""

    def __init__(self, key: bytes | Callable[[], bytes]) -> None:
        if isinstance(key, bytes) and len(key) != 32:
            raise ValueError("continuation encryption key must contain 256 bits")
        self._key = key

    def encrypt(
        self, *, metadata: dict[str, Any], payload: dict[str, Any]
    ) -> EncryptedContinuation:
        plaintext = _canonical(payload)
        nonce = os.urandom(12)
        ciphertext = self._cipher().encrypt(nonce, plaintext, _canonical(metadata))
        return EncryptedContinuation(
            nonce=nonce,
            ciphertext=ciphertext,
            payload_sha256=hashlib.sha256(plaintext).hexdigest(),
        )

    def decrypt(
        self,
        *,
        metadata: dict[str, Any],
        nonce: bytes,
        ciphertext: bytes,
        payload_sha256: str,
    ) -> dict[str, Any]:
        try:
            plaintext = self._cipher().decrypt(nonce, ciphertext, _canonical(metadata))
        except (InvalidTag, ValueError) as error:
            raise ProviderContinuationUnavailableError(
                "provider continuation authentication failed"
            ) from error
        if hashlib.sha256(plaintext).hexdigest() != payload_sha256:
            raise ProviderContinuationUnavailableError("provider continuation digest mismatch")
        try:
            payload = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderContinuationUnavailableError(
                "provider continuation payload is invalid"
            ) from error
        if not isinstance(payload, dict):
            raise ProviderContinuationUnavailableError(
                "provider continuation payload is not an object"
            )
        return payload

    def __repr__(self) -> str:
        return "ContinuationCipher(key=<redacted>)"

    def _cipher(self) -> AESGCM:
        try:
            key = self._key() if callable(self._key) else self._key
        except Exception as error:
            raise ProviderContinuationUnavailableError(
                "provider continuation encryption key is unavailable"
            ) from error
        if len(key) != 32:
            raise ProviderContinuationUnavailableError(
                "provider continuation encryption key is invalid"
            )
        return AESGCM(key)


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
