from collections.abc import Iterable

from weatherflow.capabilities.catalog import CapabilityCatalog
from weatherflow.capabilities.models import ToolSpec
from weatherflow.trust.policy import SupervisedPolicy
from weatherflow.workspaces import Workspace


class CapabilityResolver:
    def __init__(self, policy: SupervisedPolicy) -> None:
        self.policy = policy

    def resolve(
        self,
        *,
        catalog: CapabilityCatalog,
        workspace: Workspace,
        requested_tool_ids: Iterable[str],
        allowed_tool_ids: Iterable[str] | None = None,
    ) -> tuple[ToolSpec, ...]:
        selected = catalog.select(requested_tool_ids)
        if allowed_tool_ids is not None:
            allowed = frozenset(allowed_tool_ids)
            selected = tuple(tool for tool in selected if tool.tool_id in allowed)
        return tuple(self.policy.visible(selected, workspace))
