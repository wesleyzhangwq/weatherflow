import json
import socket
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

NATIVE_CREDENTIAL_NAMES = {
    "minimax": "api_key",
    "deepseek": "api_key",
    "moonshot": "api_key",
    "qwen": "api_key",
    "zhipu": "api_key",
    "siliconflow": "api_key",
    "stepfun": "api_key",
    "composio": "project_api_key",
    "provider_continuations": "encryption_key_v1",
}


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

    def delete(self, reference: CredentialRef) -> None: ...


class MappingCredentialStore:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def resolve(self, reference: CredentialRef) -> str | None:
        return self._values.get(reference.key)

    def __repr__(self) -> str:
        return f"MappingCredentialStore(keys={sorted(self._values)})"


class NativeCredentialResolver:
    """Read-only client for Tauri's private provider credential socket."""

    def __init__(
        self,
        *,
        socket_path: Path,
        token: str,
        timeout_seconds: float = 1.0,
    ) -> None:
        if not socket_path.is_absolute():
            raise ValueError("credential socket path must be absolute")
        if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
            raise ValueError("credential token must be a 256-bit lowercase hex value")
        if not 0 < timeout_seconds <= 5:
            raise ValueError("credential timeout must be bounded")
        self._socket_path = socket_path
        self._token = token
        self._timeout_seconds = timeout_seconds

    def resolve(self, reference: CredentialRef) -> str | None:
        expected_name = NATIVE_CREDENTIAL_NAMES.get(reference.provider)
        if expected_name is None or reference.name != expected_name:
            raise CredentialUnavailableError(reference.key)
        request = (
            json.dumps(
                {
                    "operation": "resolve",
                    "provider": reference.provider,
                    "token": self._token,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            + b"\n"
        )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self._timeout_seconds)
                connection.connect(str(self._socket_path))
                connection.sendall(request)
                with connection.makefile("rb") as reader:
                    raw_response = reader.readline(12_001)
            if not raw_response.endswith(b"\n") or len(raw_response) > 12_000:
                raise ValueError("invalid native credential response size")
            response = json.loads(raw_response)
            if response.get("ok") is True:
                secret = response.get("secret")
                if not isinstance(secret, str) or not secret or len(secret) > 10_000:
                    raise ValueError("invalid native credential response")
                return secret
            if response.get("code") == "not_found":
                return None
            raise CredentialUnavailableError(reference.key)
        except CredentialUnavailableError:
            raise
        except Exception as error:
            raise CredentialUnavailableError(reference.key) from error

    def __repr__(self) -> str:
        return "NativeCredentialResolver(socket=<private>, token=<redacted>)"


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


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
        try:
            return self._backend.get_password(
                f"{self._service_prefix}.{reference.provider}", reference.name
            )
        except CredentialUnavailableError:
            raise
        except Exception as error:
            # Keychain backends can reject a daemon after its unsigned development
            # executable changes. Keep backend details out of Runs and turn this into
            # the same recoverable condition as a missing credential.
            raise CredentialUnavailableError(reference.key) from error

    def set(self, reference: CredentialRef, secret: str) -> None:
        if not secret or len(secret) > 10_000:
            raise ValueError("credential must be a bounded non-empty value")
        try:
            self._backend.set_password(
                f"{self._service_prefix}.{reference.provider}",
                reference.name,
                secret,
            )
        except CredentialUnavailableError:
            raise
        except Exception as error:
            raise CredentialUnavailableError(reference.key) from error

    def delete(self, reference: CredentialRef) -> None:
        try:
            self._backend.delete_password(
                f"{self._service_prefix}.{reference.provider}", reference.name
            )
        except CredentialUnavailableError:
            raise
        except Exception as error:
            raise CredentialUnavailableError(reference.key) from error

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
        try:
            return await transport(secret)
        finally:
            del secret

    def __repr__(self) -> str:
        return "CredentialBroker(store=<redacted>)"
