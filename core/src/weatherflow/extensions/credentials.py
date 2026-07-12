from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class CredentialRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")

    @property
    def key(self) -> str:
        return f"{self.provider}.{self.name}"


class CredentialUnavailableError(LookupError):
    pass


class CredentialStore(Protocol):
    def resolve(self, reference: CredentialRef) -> str | None: ...


class WritableCredentialStore(CredentialStore, Protocol):
    def set(self, reference: CredentialRef, secret: str) -> None: ...


class MappingCredentialStore:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def resolve(self, reference: CredentialRef) -> str | None:
        return self._values.get(reference.key)

    def __repr__(self) -> str:
        return f"MappingCredentialStore(keys={sorted(self._values)})"


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...


class KeyringCredentialStore:
    def __init__(
        self,
        *,
        backend: KeyringBackend | None = None,
        service_prefix: str = "ai.weatherflow",
    ) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._backend = backend
        self._service_prefix = service_prefix

    def resolve(self, reference: CredentialRef) -> str | None:
        return self._backend.get_password(
            f"{self._service_prefix}.{reference.provider}", reference.name
        )

    def set(self, reference: CredentialRef, secret: str) -> None:
        if not secret or len(secret) > 10_000:
            raise ValueError("credential must be a bounded non-empty value")
        self._backend.set_password(
            f"{self._service_prefix}.{reference.provider}",
            reference.name,
            secret,
        )

    def __repr__(self) -> str:
        return f"KeyringCredentialStore(prefix={self._service_prefix!r}, backend=<redacted>)"


class CredentialBroker:
    def __init__(self, store: CredentialStore) -> None:
        self._store = store

    async def call(
        self,
        reference: CredentialRef,
        transport: Callable[[str], Awaitable[T]],
    ) -> T:
        secret = self._store.resolve(reference)
        if secret is None:
            raise CredentialUnavailableError(reference.key)
        return await transport(secret)

    def __repr__(self) -> str:
        return "CredentialBroker(store=<redacted>)"
