from weatherflow.runtime.protocols import ToolExecutor


class DuplicateToolExecutor(ValueError):
    pass


class ToolExecutorNotFound(LookupError):
    pass


class ToolExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, ToolExecutor] = {}

    def register(self, tool_id: str, executor: ToolExecutor) -> None:
        if tool_id in self._executors:
            raise DuplicateToolExecutor(tool_id)
        self._executors[tool_id] = executor

    def get(self, tool_id: str) -> ToolExecutor | None:
        return self._executors.get(tool_id)

    def require(self, tool_id: str) -> ToolExecutor:
        executor = self.get(tool_id)
        if executor is None:
            raise ToolExecutorNotFound(tool_id)
        return executor
