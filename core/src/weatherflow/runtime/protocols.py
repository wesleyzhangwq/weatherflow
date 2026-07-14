from typing import Any, Protocol

from weatherflow.capabilities.models import ToolSpec
from weatherflow.runtime.models import (
    ModelCompletion,
    ModelRequest,
    ModelTurn,
    ToolExecutionContext,
    ToolExecutionResult,
)


class ModelAdapter(Protocol):
    async def complete(self, request: ModelRequest) -> ModelTurn | ModelCompletion: ...


class ModelRouteUnavailableError(LookupError):
    pass


class ModelConfigurationRequiredError(ModelRouteUnavailableError):
    pass


class PublicToolError(RuntimeError):
    """A reviewed value-free tool diagnostic that may enter model context."""

    def __init__(self, code: str) -> None:
        if (
            not 2 <= len(code) <= 64
            or not code[0].isalpha()
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in code)
        ):
            raise ValueError("public tool error code must be bounded lowercase snake case")
        self.code = code
        super().__init__(code.replace("_", " "))


class ModelResolver(Protocol):
    async def resolve(self, run_id: str) -> ModelAdapter | None: ...


class ModelRouteBinder(Protocol):
    async def clone_run_route(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        workspace_id: str,
    ) -> object: ...


class ConnectorRouteBinder(Protocol):
    async def clone_run_routes(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        workspace_id: str,
    ) -> object: ...


class ToolExecutor(Protocol):
    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...
