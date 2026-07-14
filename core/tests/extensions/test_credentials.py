import json
import socket
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from weatherflow.extensions import (
    CredentialBroker,
    CredentialRef,
    CredentialUnavailableError,
    KeyringCredentialStore,
    MappingCredentialStore,
    NativeCredentialResolver,
)


async def test_credential_value_exists_only_inside_transport_callback() -> None:
    broker = CredentialBroker(MappingCredentialStore({"github.release": "super-secret-token"}))
    reference = CredentialRef(provider="github", name="release")
    observed: list[str] = []

    async def transport(secret: str) -> str:
        observed.append(secret)
        return "published"

    result = await broker.call(reference, transport)

    assert result == "published"
    assert observed == ["super-secret-token"]
    assert "super-secret-token" not in reference.model_dump_json()
    assert "super-secret-token" not in repr(broker)


async def test_missing_credential_fails_with_reference_only() -> None:
    broker = CredentialBroker(MappingCredentialStore({}))
    reference = CredentialRef(provider="calendar", name="primary")

    with pytest.raises(CredentialUnavailableError, match="calendar.primary"):
        await broker.call(reference, lambda secret: None)


def test_keyring_store_can_delete_a_broker_credential() -> None:
    class Backend:
        def __init__(self) -> None:
            self.values: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self.values.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self.values[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            self.values.pop((service, username), None)

    backend = Backend()
    store = KeyringCredentialStore(backend=backend)
    reference = CredentialRef(provider="composio", name="project_api_key")
    store.set(reference, "sensitive")

    store.delete(reference)

    assert store.resolve(reference) is None


def test_keyring_access_failure_is_exposed_as_credential_unavailable() -> None:
    class DeniedBackend:
        def get_password(self, service: str, username: str) -> str | None:
            raise RuntimeError("private keychain backend detail")

        def set_password(self, service: str, username: str, password: str) -> None:
            raise AssertionError("not used")

        def delete_password(self, service: str, username: str) -> None:
            raise AssertionError("not used")

    reference = CredentialRef(provider="minimax", name="api_key.denied")
    store = KeyringCredentialStore(backend=DeniedBackend())

    with pytest.raises(CredentialUnavailableError, match=reference.key) as caught:
        store.resolve(reference)

    assert "private keychain backend detail" not in str(caught.value)


def test_native_resolver_uses_provider_only_over_private_socket(tmp_path) -> None:
    socket_path = Path("/tmp") / f"wf-credential-{uuid4().hex[:12]}.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    received: list[dict[str, str]] = []

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            request = json.loads(connection.makefile("rb").readline())
            received.append(request)
            connection.sendall(b'{"ok":true,"secret":"native-secret"}\n')
        listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    resolver = NativeCredentialResolver(
        socket_path=socket_path,
        token="a" * 64,
    )

    value = resolver.resolve(CredentialRef(provider="minimax", name="api_key"))

    thread.join(timeout=2)
    socket_path.unlink(missing_ok=True)
    assert value == "native-secret"
    assert received == [{"operation": "resolve", "provider": "minimax", "token": "a" * 64}]
    assert "native-secret" not in repr(resolver)
    assert "a" * 64 not in repr(resolver)


def test_native_resolver_rejects_arbitrary_provider_and_key_name(tmp_path) -> None:
    resolver = NativeCredentialResolver(
        socket_path=tmp_path / "unused.sock",
        token="b" * 64,
    )

    with pytest.raises(CredentialUnavailableError, match="calendar.primary"):
        resolver.resolve(CredentialRef(provider="calendar", name="primary"))
    with pytest.raises(CredentialUnavailableError, match="minimax.other"):
        resolver.resolve(CredentialRef(provider="minimax", name="other"))


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_native_resolver_accepts_fixed_foreign_model_providers(provider: str) -> None:
    socket_path = Path("/tmp") / f"wf-credential-{uuid4().hex[:12]}.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    received: list[dict[str, str]] = []

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            received.append(json.loads(connection.makefile("rb").readline()))
            connection.sendall(b'{"ok":true,"secret":"native-secret"}\n')
        listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    resolver = NativeCredentialResolver(socket_path=socket_path, token="e" * 64)

    assert resolver.resolve(CredentialRef(provider=provider, name="api_key")) == "native-secret"

    thread.join(timeout=2)
    socket_path.unlink(missing_ok=True)
    assert received == [{"operation": "resolve", "provider": provider, "token": "e" * 64}]


def test_native_resolver_allows_only_the_fixed_internal_continuation_key(tmp_path) -> None:
    socket_path = Path("/tmp") / f"wf-credential-{uuid4().hex[:12]}.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    received: list[dict[str, str]] = []

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            received.append(json.loads(connection.makefile("rb").readline()))
            connection.sendall(b'{"ok":true,"secret":"' + b"a" * 64 + b'"}\n')
        listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    resolver = NativeCredentialResolver(socket_path=socket_path, token="d" * 64)

    key = resolver.resolve(
        CredentialRef(provider="provider_continuations", name="encryption_key_v1")
    )

    thread.join(timeout=2)
    socket_path.unlink(missing_ok=True)
    assert key == "a" * 64
    assert received == [
        {
            "operation": "resolve",
            "provider": "provider_continuations",
            "token": "d" * 64,
        }
    ]


def test_native_resolver_fails_closed_without_leaking_broker_response(tmp_path) -> None:
    socket_path = Path("/tmp") / f"wf-credential-{uuid4().hex[:12]}.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            connection.makefile("rb").readline()
            connection.sendall(
                b'{"ok":false,"code":"unauthorized","detail":"private-native-detail"}\n'
            )
        listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    resolver = NativeCredentialResolver(socket_path=socket_path, token="c" * 64)

    with pytest.raises(CredentialUnavailableError) as caught:
        resolver.resolve(CredentialRef(provider="minimax", name="api_key"))

    thread.join(timeout=2)
    socket_path.unlink(missing_ok=True)
    assert "private-native-detail" not in str(caught.value)
