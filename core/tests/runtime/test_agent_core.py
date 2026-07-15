import pytest

from weatherflow.runtime import (
    AgentCore,
    AgentCoreEventKind,
    AgentDefinition,
    DelegationTurn,
    FinalTurn,
    LeafDelegationError,
    ModelRequest,
)


class ScriptedModel:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def request(*, leaf: bool = False) -> ModelRequest:
    return ModelRequest(
        run_id="run-1",
        agent=AgentDefinition(
            agent_id="worker" if leaf else "orchestrator",
            system_prompt="Complete the task",
            is_leaf=leaf,
        ),
        messages=(),
        tools=(),
    )


async def test_agent_core_normalizes_a_bare_model_turn() -> None:
    model = ScriptedModel([FinalTurn(content="done")])

    completion = await AgentCore(retry_base_delay_seconds=0).next_turn(
        request(),
        model,
    )

    assert completion.turn == FinalTurn(content="done")
    assert model.requests[0].run_id == "run-1"


async def test_agent_core_emits_bounded_retry_events_before_success() -> None:
    model = ScriptedModel([TimeoutError(), ConnectionError(), FinalTurn(content="done")])
    events = []

    async def emit(event) -> None:
        events.append(event)

    completion = await AgentCore(retry_base_delay_seconds=0).next_turn(
        request(),
        model,
        emit=emit,
    )

    assert completion.turn == FinalTurn(content="done")
    assert [event.kind for event in events] == [
        AgentCoreEventKind.MODEL_START,
        AgentCoreEventKind.MODEL_RETRY,
        AgentCoreEventKind.MODEL_START,
        AgentCoreEventKind.MODEL_RETRY,
        AgentCoreEventKind.MODEL_START,
        AgentCoreEventKind.MODEL_END,
    ]
    assert [event.attempt for event in events] == [1, 1, 2, 2, 3, 3]
    assert all(event.max_attempts == 3 for event in events)
    assert events[-1].turn_kind == "final"


async def test_agent_core_raises_after_the_bounded_retry_limit() -> None:
    model = ScriptedModel([TimeoutError(), TimeoutError(), TimeoutError()])
    events = []

    async def emit(event) -> None:
        events.append(event)

    with pytest.raises(TimeoutError):
        await AgentCore(retry_base_delay_seconds=0).next_turn(
            request(),
            model,
            emit=emit,
        )

    assert len(model.requests) == 3
    assert events[-1].kind is AgentCoreEventKind.MODEL_ERROR
    assert events[-1].attempt == 3


async def test_agent_core_enforces_leaf_agent_constraints() -> None:
    model = ScriptedModel([DelegationTurn(agent_id="researcher", task="continue")])

    with pytest.raises(LeafDelegationError):
        await AgentCore(retry_base_delay_seconds=0).next_turn(
            request(leaf=True),
            model,
        )
