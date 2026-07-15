import asyncio
from typing import Protocol

from weatherflow.sandbox.models import SandboxRequest, SandboxResult


class SandboxBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    def is_available(self) -> bool: ...

    async def execute(self, request: SandboxRequest) -> SandboxResult: ...


class SandboxStdioProcess(Protocol):
    @property
    def stdin(self) -> asyncio.StreamWriter | None: ...

    @property
    def stdout(self) -> asyncio.StreamReader | None: ...

    @property
    def returncode(self) -> int | None: ...

    async def close(self) -> None: ...


class SandboxStdioBackend(SandboxBackend, Protocol):
    async def spawn_stdio(self, request: SandboxRequest) -> SandboxStdioProcess: ...
