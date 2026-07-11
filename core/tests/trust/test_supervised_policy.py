from pathlib import Path

import pytest

from weatherflow.capabilities import ToolEffect, ToolHealth, ToolSpec
from weatherflow.trust import DecisionKind, SupervisedPolicy
from weatherflow.workspaces import Workspace


def workspace(tmp_path: Path, scopes: set[str] | None = None) -> Workspace:
    return Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes=scopes or set(),
    )


def tool(
    effect: ToolEffect,
    *,
    tool_id: str | None = None,
    scopes: set[str] | None = None,
    health: ToolHealth = ToolHealth.AVAILABLE,
) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id or effect.value,
        description="test tool",
        input_schema={},
        output_schema={},
        effect=effect,
        required_scopes=frozenset(scopes or set()),
        source="test",
        source_version="1",
        health=health,
    )


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (ToolEffect.OBSERVE, DecisionKind.ALLOW),
        (ToolEffect.NETWORK_READ, DecisionKind.ALLOW),
        (ToolEffect.WORKSPACE_WRITE, DecisionKind.SANDBOX),
        (ToolEffect.EXECUTE, DecisionKind.SANDBOX),
        (ToolEffect.EXTERNAL_WRITE, DecisionKind.APPROVE),
        (ToolEffect.INSTALL, DecisionKind.APPROVE),
        (ToolEffect.DESTRUCTIVE, DecisionKind.APPROVE),
        (ToolEffect.SENSITIVE, DecisionKind.APPROVE),
    ],
)
def test_default_effect_table(tmp_path: Path, effect: ToolEffect, expected: DecisionKind) -> None:
    decision = SupervisedPolicy().evaluate(tool(effect), workspace(tmp_path))

    assert decision.kind is expected


def test_missing_scope_fails_closed_before_effect_rule(tmp_path: Path) -> None:
    decision = SupervisedPolicy().evaluate(
        tool(ToolEffect.OBSERVE, scopes={"calendar:read"}),
        workspace(tmp_path),
    )

    assert decision.kind is DecisionKind.DENY
    assert decision.missing_scopes == frozenset({"calendar:read"})


def test_unavailable_tool_is_hidden(tmp_path: Path) -> None:
    decision = SupervisedPolicy().evaluate(
        tool(ToolEffect.OBSERVE, health=ToolHealth.UNAVAILABLE),
        workspace(tmp_path),
    )

    assert decision.kind is DecisionKind.HIDE


def test_visible_preserves_order_and_excludes_denied_or_hidden(tmp_path: Path) -> None:
    tools = [
        tool(ToolEffect.OBSERVE, tool_id="allow"),
        tool(ToolEffect.EXECUTE, tool_id="sandbox"),
        tool(ToolEffect.EXTERNAL_WRITE, tool_id="approve"),
        tool(ToolEffect.OBSERVE, tool_id="deny", scopes={"missing"}),
        tool(ToolEffect.OBSERVE, tool_id="hide", health=ToolHealth.UNAVAILABLE),
    ]

    visible = SupervisedPolicy().visible(tools, workspace(tmp_path))

    assert [item.tool_id for item in visible] == ["allow", "sandbox", "approve"]
