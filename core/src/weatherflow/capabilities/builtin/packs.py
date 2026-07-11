from collections.abc import Iterable

from weatherflow.capabilities.builtin.developer import developer_tool_specs
from weatherflow.capabilities.builtin.operations import (
    calendar_tool_specs,
    github_tool_specs,
)
from weatherflow.capabilities.builtin.personal import personal_tool_specs
from weatherflow.capabilities.builtin.research import research_tool_specs
from weatherflow.capabilities.models import ToolHealth, ToolSpec

DEVELOPER_PACK = "developer"
RESEARCH_PACK = "research"
PERSONAL_OPERATIONS_PACK = "personal_operations"

BUILTIN_PACK_TOOL_IDS: dict[str, frozenset[str]] = {
    DEVELOPER_PACK: frozenset(
        {
            *(tool.tool_id for tool in developer_tool_specs()),
            *(tool.tool_id for tool in github_tool_specs()),
        }
    ),
    RESEARCH_PACK: frozenset(tool.tool_id for tool in research_tool_specs()),
    PERSONAL_OPERATIONS_PACK: frozenset(
        {
            *(tool.tool_id for tool in calendar_tool_specs()),
            *(tool.tool_id for tool in personal_tool_specs()),
        }
    ),
}


class UnknownCapabilityPackError(LookupError):
    pass


def builtin_tool_specs(
    *,
    research_available: bool,
    calendar_available: bool,
    github_available: bool,
) -> tuple[ToolSpec, ...]:
    return (
        *developer_tool_specs(),
        *_with_health(github_tool_specs(), github_available),
        *_with_health(research_tool_specs(), research_available),
        *_with_health(calendar_tool_specs(), calendar_available),
        *_with_personal_health(personal_tool_specs(), calendar_available),
    )


def tool_ids_for_installed_packs(installed_packs: Iterable[str]) -> frozenset[str]:
    selected: set[str] = set()
    for pack in installed_packs:
        tool_ids = BUILTIN_PACK_TOOL_IDS.get(pack)
        if tool_ids is None:
            raise UnknownCapabilityPackError(pack)
        selected.update(tool_ids)
    return frozenset(selected)


def _with_health(tools: tuple[ToolSpec, ...], available: bool) -> tuple[ToolSpec, ...]:
    if available:
        return tools
    return tuple(tool.model_copy(update={"health": ToolHealth.UNAVAILABLE}) for tool in tools)


def _with_personal_health(
    tools: tuple[ToolSpec, ...], calendar_available: bool
) -> tuple[ToolSpec, ...]:
    if calendar_available:
        return tools
    return tuple(
        tool
        if tool.tool_id == "personal.plan_day"
        else tool.model_copy(update={"health": ToolHealth.UNAVAILABLE})
        for tool in tools
    )
