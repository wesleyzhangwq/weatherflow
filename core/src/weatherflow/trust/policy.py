from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities.models import ToolEffect, ToolHealth, ToolSpec
from weatherflow.workspaces import Workspace


class DecisionKind(StrEnum):
    ALLOW = "allow"
    SANDBOX = "sandbox"
    APPROVE = "approve"
    DENY = "deny"
    HIDE = "hide"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    reason: str
    missing_scopes: frozenset[str] = frozenset()


EFFECT_DECISIONS: dict[ToolEffect, DecisionKind] = {
    ToolEffect.OBSERVE: DecisionKind.ALLOW,
    ToolEffect.NETWORK_READ: DecisionKind.ALLOW,
    ToolEffect.WORKSPACE_WRITE: DecisionKind.SANDBOX,
    ToolEffect.EXECUTE: DecisionKind.SANDBOX,
    ToolEffect.EXTERNAL_WRITE: DecisionKind.APPROVE,
    ToolEffect.INSTALL: DecisionKind.APPROVE,
    ToolEffect.DESTRUCTIVE: DecisionKind.APPROVE,
    ToolEffect.SENSITIVE: DecisionKind.APPROVE,
}


class SupervisedPolicy:
    def evaluate(self, tool: ToolSpec, workspace: Workspace) -> PolicyDecision:
        if tool.health is ToolHealth.UNAVAILABLE:
            return PolicyDecision(kind=DecisionKind.HIDE, reason="tool unavailable")
        missing = tool.required_scopes - workspace.granted_scopes
        if missing:
            return PolicyDecision(
                kind=DecisionKind.DENY,
                reason="required scopes are not granted",
                missing_scopes=missing,
            )
        kind = EFFECT_DECISIONS[tool.effect]
        return PolicyDecision(kind=kind, reason=f"supervised policy: {tool.effect.value}")

    def visible(self, tools: Sequence[ToolSpec], workspace: Workspace) -> list[ToolSpec]:
        excluded = {DecisionKind.DENY, DecisionKind.HIDE}
        return [tool for tool in tools if self.evaluate(tool, workspace).kind not in excluded]
