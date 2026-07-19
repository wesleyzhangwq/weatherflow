from collections.abc import Iterable

from weatherflow.capabilities.builtin.activity import activity_tool_specs
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
CORE_TOOL_IDS = frozenset(tool.tool_id for tool in activity_tool_specs())

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
        *activity_tool_specs(),
        *developer_tool_specs(),
        *_when_available(github_tool_specs(), github_available),
        *_when_available(research_tool_specs(), research_available),
        *_with_health(calendar_tool_specs(), calendar_available),
        *_with_personal_health(personal_tool_specs(), calendar_available),
    )


def tool_ids_for_installed_packs(installed_packs: Iterable[str]) -> frozenset[str]:
    selected: set[str] = set(CORE_TOOL_IDS)
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


def _when_available(tools: tuple[ToolSpec, ...], available: bool) -> tuple[ToolSpec, ...]:
    """Do not advertise legacy provider tools without a reviewed backend.

    GitHub conversation actions are owned by the canonical Composio tool set.
    Research remains an injectable typed-provider capability. Registering ghost
    ToolSpecs as permanently unavailable made the production catalog misleading.
    """

    return tools if available else ()


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
