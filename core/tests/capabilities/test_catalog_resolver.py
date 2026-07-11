from pathlib import Path

import pytest

from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    DuplicateToolError,
    ToolEffect,
    ToolHealth,
    ToolSpec,
    UnknownToolError,
)
from weatherflow.trust import SupervisedPolicy
from weatherflow.workspaces import Workspace


def tool(
    tool_id: str,
    effect: ToolEffect = ToolEffect.OBSERVE,
    *,
    scopes: set[str] | None = None,
    health: ToolHealth = ToolHealth.AVAILABLE,
) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description=tool_id,
        input_schema={},
        output_schema={},
        effect=effect,
        required_scopes=frozenset(scopes or set()),
        source="test",
        source_version="1",
        health=health,
    )


def workspace(tmp_path: Path) -> Workspace:
    return Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"github:write"},
    )


def test_catalog_rejects_duplicates_and_sorts_selection() -> None:
    catalog = CapabilityCatalog([tool("z"), tool("a")])

    assert [item.tool_id for item in catalog.all()] == ["a", "z"]
    assert [item.tool_id for item in catalog.select(["z", "a"])] == ["a", "z"]
    with pytest.raises(DuplicateToolError):
        catalog.register(tool("a"))
    with pytest.raises(UnknownToolError):
        catalog.select(["missing"])


def test_resolver_intersects_request_filter_and_authority(tmp_path: Path) -> None:
    catalog = CapabilityCatalog(
        [
            tool("observe"),
            tool("approve", ToolEffect.EXTERNAL_WRITE, scopes={"github:write"}),
            tool("denied", scopes={"calendar:read"}),
            tool("hidden", health=ToolHealth.UNAVAILABLE),
            tool("filtered"),
        ]
    )
    resolver = CapabilityResolver(SupervisedPolicy())

    resolved = resolver.resolve(
        catalog=catalog,
        workspace=workspace(tmp_path),
        requested_tool_ids={"observe", "approve", "denied", "hidden", "filtered"},
        allowed_tool_ids={"observe", "approve", "denied", "hidden"},
    )

    assert [item.tool_id for item in resolved] == ["approve", "observe"]
