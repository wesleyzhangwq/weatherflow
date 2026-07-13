import io
from pathlib import Path

import pytest
from pydantic import ValidationError

from weatherflow.api.desktop_bootstrap import DesktopBootstrap, watch_parent_disconnect


def payload(**overrides: object) -> bytes:
    values = {
        "version": 1,
        "bridge_token": "a" * 64,
        "credential_socket": "/tmp/weatherflow-credential.sock",
        "credential_token": "b" * 64,
    }
    values.update(overrides)
    import json

    return (json.dumps(values) + "\n").encode()


def test_desktop_bootstrap_is_bounded_strict_and_redacted() -> None:
    bootstrap = DesktopBootstrap.read(io.BytesIO(payload()))

    assert bootstrap.credential_socket == Path("/tmp/weatherflow-credential.sock")
    assert bootstrap.bridge_token == "a" * 64
    assert "a" * 64 not in repr(bootstrap)
    assert "b" * 64 not in repr(bootstrap)


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 2},
        {"credential_socket": "relative.sock"},
        {"credential_token": "short"},
        {"arbitrary_secret_name": "not-allowed"},
    ],
)
def test_desktop_bootstrap_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises((ValueError, ValidationError)):
        DesktopBootstrap.read(io.BytesIO(payload(**overrides)))


def test_desktop_bootstrap_rejects_oversized_or_unterminated_input() -> None:
    with pytest.raises(ValueError):
        DesktopBootstrap.read(io.BytesIO(b"{" + b"x" * 5000 + b"}\n"))
    with pytest.raises(ValueError):
        DesktopBootstrap.read(io.BytesIO(payload().rstrip(b"\n")))


def test_parent_pipe_eof_triggers_daemon_shutdown_callback() -> None:
    disconnected: list[bool] = []

    thread = watch_parent_disconnect(
        io.BytesIO(b""), on_disconnect=lambda: disconnected.append(True)
    )
    thread.join(timeout=1)

    assert disconnected == [True]
