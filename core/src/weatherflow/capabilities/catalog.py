from collections.abc import Iterable

from weatherflow.capabilities.models import ToolSpec


class DuplicateToolError(ValueError):
    pass


class UnknownToolError(LookupError):
    pass


class CapabilityCatalog:
    def __init__(self, tools: Iterable[ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if tool.tool_id in self._tools:
            raise DuplicateToolError(tool.tool_id)
        self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._tools.get(tool_id)

    def select(self, tool_ids: Iterable[str]) -> tuple[ToolSpec, ...]:
        selected: list[ToolSpec] = []
        for tool_id in set(tool_ids):
            tool = self.get(tool_id)
            if tool is None:
                raise UnknownToolError(tool_id)
            selected.append(tool)
        return tuple(sorted(selected, key=lambda item: item.tool_id))

    def all(self) -> tuple[ToolSpec, ...]:
        return tuple(sorted(self._tools.values(), key=lambda item: item.tool_id))
