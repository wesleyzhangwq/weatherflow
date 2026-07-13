import secrets
from typing import Any, Protocol

PROVIDER_CONTINUATION_PROVIDER = "provider_continuations"
PROVIDER_CONTINUATION_NAME = "encryption_key_v1"


class ContinuationCredentialStore(Protocol):
    def resolve(self, reference: Any) -> str | None: ...


def resolve_provider_continuation_key(store: ContinuationCredentialStore) -> bytes:
    from weatherflow.extensions.credentials import CredentialRef, CredentialUnavailableError

    reference = CredentialRef(
        provider=PROVIDER_CONTINUATION_PROVIDER,
        name=PROVIDER_CONTINUATION_NAME,
    )
    secret = store.resolve(reference)
    if secret is None:
        setter = getattr(store, "set", None)
        if setter is None:
            raise CredentialUnavailableError(reference.key)
        secret = secrets.token_hex(32)
        setter(reference, secret)
    if len(secret) != 64:
        raise CredentialUnavailableError(reference.key)
    try:
        key = bytes.fromhex(secret)
    except ValueError as error:
        raise CredentialUnavailableError(reference.key) from error
    if len(key) != 32:
        raise CredentialUnavailableError(reference.key)
    return key
