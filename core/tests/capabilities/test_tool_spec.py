import pytest
from pydantic import ValidationError

from weatherflow.capabilities import (
    IdempotencyKind,
    ToolEffect,
    ToolHealth,
    ToolSpec,
)


def tool_values() -> dict[str, object]:
    return {
        "tool_id": "files.write",
        "description": "Write a file inside the workspace",
        "input_schema": {"type": "object", "required": ["path"]},
        "output_schema": {"type": "object"},
        "effect": "workspace_write",
        "required_scopes": ["workspace:write"],
        "idempotency": "key",
        "timeout_seconds": 30,
        "source": "builtin",
        "source_version": "3.0.0a1",
        "health": "available",
    }


def test_tool_spec_normalizes_the_canonical_contract() -> None:
    tool = ToolSpec.model_validate(tool_values())

    assert tool.effect is ToolEffect.WORKSPACE_WRITE
    assert tool.required_scopes == frozenset({"workspace:write"})
    assert tool.idempotency is IdempotencyKind.KEY
    assert tool.health is ToolHealth.AVAILABLE
    assert set(tool.model_dump()) == {
        "tool_id",
        "description",
        "input_schema",
        "output_schema",
        "effect",
        "required_scopes",
        "idempotency",
        "timeout_seconds",
        "source",
        "source_version",
        "health",
    }


def test_tool_spec_is_frozen() -> None:
    tool = ToolSpec.model_validate(tool_values())

    with pytest.raises(ValidationError):
        tool.health = ToolHealth.DEGRADED


def test_unknown_effect_is_rejected() -> None:
    values = tool_values()
    values["effect"] = "mystery"

    with pytest.raises(ValidationError):
        ToolSpec.model_validate(values)
