from typing import Any, Protocol

from weatherflow.capabilities.models import ToolSpec
from weatherflow.runtime.models import (
    ModelRequest,
    ModelTurn,
    ToolExecutionContext,
    ToolExecutionResult,
)


class ModelAdapter(Protocol):
    async def complete(self, request: ModelRequest) -> ModelTurn: ...


class ToolExecutor(Protocol):
    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...
