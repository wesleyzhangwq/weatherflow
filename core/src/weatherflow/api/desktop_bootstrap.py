import json
import os
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BOOTSTRAP_BYTES = 4096
TOKEN_PATTERN = r"^[0-9a-f]{64}$"


class DesktopBootstrap(BaseModel):
    """One-shot process bootstrap received from the owning Tauri process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    bridge_token: str = Field(pattern=TOKEN_PATTERN)
    credential_socket: Path
    credential_token: str = Field(pattern=TOKEN_PATTERN)

    @field_validator("credential_socket")
    @classmethod
    def socket_is_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("credential socket path must be absolute")
        return value

    @classmethod
    def read(cls, stream: BinaryIO) -> "DesktopBootstrap":
        raw = stream.readline(MAX_BOOTSTRAP_BYTES + 1)
        if not raw.endswith(b"\n") or len(raw) > MAX_BOOTSTRAP_BYTES:
            raise ValueError("invalid desktop bootstrap")
        try:
            return cls.model_validate(json.loads(raw))
        except Exception as error:
            raise ValueError("invalid desktop bootstrap") from error

    def __repr__(self) -> str:
        return (
            "DesktopBootstrap(version=1, bridge_token=<redacted>, "
            "credential_socket=<private>, credential_token=<redacted>)"
        )


def watch_parent_disconnect(
    stream: BinaryIO,
    *,
    on_disconnect: Callable[[], None] | None = None,
) -> threading.Thread:
    """Terminate the daemon when its owning Tauri process closes stdin."""

    disconnect = on_disconnect or (lambda: os.kill(os.getpid(), signal.SIGTERM))

    def wait_for_eof() -> None:
        try:
            while stream.read(1):
                pass
        finally:
            disconnect()

    thread = threading.Thread(
        target=wait_for_eof,
        name="weatherflow-desktop-parent-watch",
        daemon=True,
    )
    thread.start()
    return thread
