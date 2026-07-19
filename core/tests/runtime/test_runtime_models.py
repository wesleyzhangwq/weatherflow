import pytest
from pydantic import TypeAdapter, ValidationError

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.runtime import (
    AgentDefinition,
    AgentMessage,
    CompactWorkerResult,
    DelegationTurn,
    FinalTurn,
    LeafDelegationError,
    MessageRole,
    ModelRequest,
    ModelTurn,
    ToolCallTurn,
)


def tool() -> ToolSpec:
    return ToolSpec(
        tool_id="files.read",
        description="Read a workspace file",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.OBSERVE,
        source="builtin",
        source_version="1",
    )


def test_model_request_round_trips_domain_contracts() -> None:
    request = ModelRequest(
        run_id="run-1",
        agent=AgentDefinition(
            agent_id="orchestrator",
            system_prompt="Complete the user goal",
            tool_filter=frozenset({"files.read"}),
        ),
        messages=(AgentMessage(role=MessageRole.USER, content="Read README"),),
        tools=(tool(),),
    )

    restored = ModelRequest.model_validate_json(request.model_dump_json())

    assert restored == request
    with pytest.raises(ValidationError):
        request.messages[0].content = "mutated"


def test_tool_free_model_request_rejects_exposed_tools() -> None:
    with pytest.raises(ValidationError, match="tool-free model requests cannot expose tools"):
        ModelRequest(
            run_id="run-restricted",
            agent=AgentDefinition(
                agent_id="orchestrator",
                system_prompt="Analyze bounded observations only",
            ),
            messages=(AgentMessage(role=MessageRole.USER, content="Summarize"),),
            tools=(tool(),),
            tool_free=True,
        )


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "final", "content": "done"},
        {"kind": "tool_call", "tool_id": "files.read", "arguments": {"path": "README"}},
        {"kind": "delegation", "agent_id": "researcher", "task": "Find sources"},
    ],
)
def test_model_turn_is_discriminated(value: dict[str, object]) -> None:
    turn = TypeAdapter(ModelTurn).validate_python(value)

    assert isinstance(turn, FinalTurn | ToolCallTurn | DelegationTurn)


def test_multi_kind_payload_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ModelTurn).validate_python(
            {"kind": "final", "content": "done", "tool_id": "files.read"}
        )


def test_leaf_agent_cannot_delegate() -> None:
    leaf = AgentDefinition(
        agent_id="worker",
        system_prompt="Research",
        is_leaf=True,
    )

    with pytest.raises(LeafDelegationError):
        leaf.validate_turn(DelegationTurn(agent_id="another", task="nested work"))


def test_delegation_and_compact_results_are_size_bounded() -> None:
    with pytest.raises(ValidationError):
        DelegationTurn(agent_id="worker", task="x" * 4_001)

    with pytest.raises(ValidationError):
        CompactWorkerResult(
            agent_id="worker",
            summary="x" * 2_001,
            status="failed",
        )
