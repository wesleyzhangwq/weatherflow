import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.continuations import ProviderContinuation
from weatherflow.extensions import CredentialBroker, CredentialRef, MappingCredentialStore
from weatherflow.models import (
    MiniMaxAdapter,
    MiniMaxAuthenticationError,
    MiniMaxResponseError,
    MiniMaxRetryableError,
    OpenAICompatibleAdapter,
)
from weatherflow.runtime import (
    AgentDefinition,
    AgentMessage,
    DelegationTurn,
    FinalTurn,
    MessageRole,
    ModelCompletion,
    ModelRequest,
    ToolCallBatchTurn,
    ToolCallTurn,
)

SECRET = "minimax-secret-never-persist"


def request(
    *messages: AgentMessage,
    leaf: bool = False,
    continuations: tuple[ProviderContinuation, ...] = (),
) -> ModelRequest:
    return ModelRequest(
        run_id="run-1",
        agent=AgentDefinition(
            agent_id="worker" if leaf else "orchestrator",
            system_prompt="Complete the explicit goal without widening authority.",
            is_leaf=leaf,
        ),
        messages=messages
        or (AgentMessage(role=MessageRole.USER, content="Read the release notes"),),
        tools=(
            ToolSpec(
                tool_id="developer.read_file",
                description="Read a scoped file",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                output_schema={"type": "object"},
                effect=ToolEffect.OBSERVE,
                source="builtin.developer",
                source_version="1",
            ),
        ),
        provider_continuations=continuations,
    )


def adapter(handler) -> MiniMaxAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MiniMaxAdapter(
        broker=CredentialBroker(MappingCredentialStore({"minimax.api_key": SECRET})),
        credential_ref=CredentialRef(provider="minimax", name="api_key"),
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1",
        client=client,
    )


def m2_adapter(handler, model: str = "MiniMax-M2.7") -> MiniMaxAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MiniMaxAdapter(
        broker=CredentialBroker(MappingCredentialStore({"minimax.api_key": SECRET})),
        credential_ref=CredentialRef(provider="minimax", name="api_key"),
        model=model,
        base_url="https://api.minimax.test/v1",
        client=client,
    )


def official_adapter(handler, model: str) -> MiniMaxAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MiniMaxAdapter(
        broker=CredentialBroker(MappingCredentialStore({"minimax.api_key": SECRET})),
        credential_ref=CredentialRef(provider="minimax", name="api_key"),
        model=model,
        base_url="https://api.minimax.io/v1",
        client=client,
    )


async def test_final_text_and_usage_are_provider_neutral() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url == "https://api.minimax.test/v1/chat/completions"
        assert http_request.headers["authorization"] == f"Bearer {SECRET}"
        body = json.loads(http_request.content)
        assert body["model"] == "MiniMax-M3"
        assert body["thinking"] == {"type": "disabled"}
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["content"].startswith(
            "Complete the explicit goal without widening authority."
        )
        assert "multiple independent tools" in body["messages"][0]["content"]
        assert body["messages"][1]["role"] == "user"
        assert all("developer.read_file" != tool["function"]["name"] for tool in body["tools"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "<think>x</think>Done"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    turn = await adapter(handler).complete(request())

    assert turn == FinalTurn(
        content="Done",
        usage={"input_tokens": 12, "output_tokens": 4},
    )


@pytest.mark.parametrize(
    ("model", "expected_cost"),
    [
        ("MiniMax-M3", 0.0000015),
        ("MiniMax-M2.7", 0.0000015),
        ("MiniMax-M2.7-highspeed", 0.000003),
        ("MiniMax-M2.5", 0.0000015),
        ("MiniMax-M2.5-highspeed", 0.000003),
        ("MiniMax-M2.1", 0.0000015),
        ("MiniMax-M2.1-highspeed", 0.000003),
        ("MiniMax-M2", 0.0000015),
    ],
)
async def test_official_minimax_models_report_paygo_equivalent_cost(
    model: str,
    expected_cost: float,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Done"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    completion = await official_adapter(handler, model).complete(request())
    turn = completion.turn if isinstance(completion, ModelCompletion) else completion

    assert isinstance(turn, FinalTurn)
    assert turn.usage.input_tokens == 1
    assert turn.usage.output_tokens == 1
    assert turn.usage.cost_usd == pytest.approx(expected_cost)


async def test_custom_minimax_origin_does_not_assume_official_pricing() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Done"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    turn = await adapter(handler).complete(request())

    assert isinstance(turn, FinalTurn)
    assert turn.usage.cost_usd is None


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"prompt_tokens": 1.5, "completion_tokens": 1},
        {"prompt_tokens": -1, "completion_tokens": 1},
    ],
)
async def test_official_minimax_invalid_usage_does_not_assume_zero_cost(
    usage: dict[str, object],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Done"}}],
                "usage": usage,
            },
        )

    adapter = official_adapter(handler, model="MiniMax-M3")
    turn = await adapter.complete(request())

    assert isinstance(turn, FinalTurn)
    assert turn.usage.input_tokens == 0
    assert turn.usage.output_tokens == 0
    assert turn.usage.cost_usd is None


async def test_generic_compatible_provider_omits_minimax_only_fields() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert body["model"] == "deepseek-v4-flash"
        assert "thinking" not in body
        assert "reasoning_split" not in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "完成"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    compatible = OpenAICompatibleAdapter(
        provider="deepseek",
        broker=CredentialBroker(MappingCredentialStore({"deepseek.api_key": SECRET})),
        credential_ref=CredentialRef(provider="deepseek", name="api_key"),
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.test/v1",
        client=client,
    )

    assert await compatible.complete(request()) == FinalTurn(content="完成")


async def test_dotted_tool_ids_round_trip_through_safe_function_names() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        function_name = next(
            tool["function"]["name"]
            for tool in body["tools"]
            if tool["function"]["description"] == "Read a scoped file"
        )
        assert "." not in function_name
        assert len(function_name) <= 64
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": function_name,
                                        "arguments": '{"path":"README.md"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    turn = await adapter(handler).complete(request())

    assert turn == ToolCallTurn(
        call_id="call-1",
        tool_id="developer.read_file",
        arguments={"path": "README.md"},
    )


async def test_multiple_provider_tool_calls_become_one_ordered_batch() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        function_name = next(
            tool["function"]["name"]
            for tool in body["tools"]
            if tool["function"]["description"] == "Read a scoped file"
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-a",
                                    "type": "function",
                                    "function": {
                                        "name": function_name,
                                        "arguments": '{"path":"A.md"}',
                                    },
                                },
                                {
                                    "id": "call-b",
                                    "type": "function",
                                    "function": {
                                        "name": function_name,
                                        "arguments": '{"path":"B.md"}',
                                    },
                                },
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3},
            },
        )

    turn = await adapter(handler).complete(request())

    assert turn == ToolCallBatchTurn(
        calls=(
            ToolCallTurn(
                call_id="call-a",
                tool_id="developer.read_file",
                arguments={"path": "A.md"},
            ),
            ToolCallTurn(
                call_id="call-b",
                tool_id="developer.read_file",
                arguments={"path": "B.md"},
            ),
        ),
        usage={"input_tokens": 8, "output_tokens": 3},
    )


async def test_tool_history_is_reconstructed_for_the_next_model_call() -> None:
    assistant_turn = AgentMessage(
        role=MessageRole.ASSISTANT,
        content=json.dumps(
            {
                "kind": "tool_call",
                "call_id": "call-1",
                "tool_id": "developer.read_file",
                "arguments": {"path": "README.md"},
                "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": None},
            }
        ),
    )
    observation = AgentMessage(
        role=MessageRole.TOOL,
        name="developer.read_file",
        tool_call_id="call-1",
        content='{"content":"WeatherFlow"}',
    )

    async def handler(http_request: httpx.Request) -> httpx.Response:
        messages = json.loads(http_request.content)["messages"]
        assert messages[-2]["role"] == "assistant"
        assert messages[-2]["tool_calls"][0]["id"] == "call-1"
        assert messages[-1] == {
            "role": "tool",
            "name": messages[-2]["tool_calls"][0]["function"]["name"],
            "tool_call_id": "call-1",
            "content": '{"content":"WeatherFlow"}',
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Summarized"}}]},
        )

    turn = await adapter(handler).complete(
        request(
            AgentMessage(role=MessageRole.USER, content="Read it"),
            assistant_turn,
            observation,
        )
    )

    assert turn == FinalTurn(content="Summarized")


async def test_m2_preserves_and_replays_the_complete_provider_assistant_message() -> None:
    assistant_message: dict = {}

    async def first_handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert body["model"] == "MiniMax-M2.7"
        assert body["reasoning_split"] is True
        assert "thinking" not in body
        function_name = next(
            tool["function"]["name"]
            for tool in body["tools"]
            if tool["function"]["description"] == "Read a scoped file"
        )
        assistant_message.update(
            {
                "role": "assistant",
                "content": None,
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "private-provider-reasoning"}
                ],
                "tool_calls": [
                    {
                        "id": "call-m2",
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            }
        )
        return httpx.Response(200, json={"choices": [{"message": assistant_message}]})

    completion = await m2_adapter(first_handler).complete(request())

    assert isinstance(completion, ModelCompletion)
    assert completion.turn == ToolCallTurn(
        call_id="call-m2",
        tool_id="developer.read_file",
        arguments={"path": "README.md"},
    )
    assert completion.continuation is not None
    assert completion.continuation.payload == assistant_message

    now = datetime(2026, 7, 13, tzinfo=UTC)
    persisted = ProviderContinuation(
        run_id="run-1",
        step_index=1,
        provider="minimax",
        model="MiniMax-M2.7",
        payload=assistant_message,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    assistant_turn = AgentMessage(
        role=MessageRole.ASSISTANT,
        content=json.dumps(completion.turn.model_dump(mode="json")),
    )
    observation = AgentMessage(
        role=MessageRole.TOOL,
        name="developer.read_file",
        tool_call_id="call-m2",
        content='{"content":"WeatherFlow"}',
    )

    async def second_handler(http_request: httpx.Request) -> httpx.Response:
        messages = json.loads(http_request.content)["messages"]
        assert messages[-2] == assistant_message
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["tool_call_id"] == "call-m2"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "完成"}}]},
        )

    final = await m2_adapter(second_handler).complete(
        request(
            AgentMessage(role=MessageRole.USER, content="Read it"),
            assistant_turn,
            observation,
            continuations=(persisted,),
        )
    )

    assert isinstance(final, ModelCompletion)
    assert final.turn == FinalTurn(content="完成")
    assert final.continuation is None


async def test_orchestrator_can_request_bounded_leaf_delegation() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        delegation = next(
            tool for tool in body["tools"] if tool["function"]["name"] == "weatherflow_delegate"
        )
        assert delegation["function"]["parameters"]["required"] == ["agent_id", "task"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "delegate-1",
                                    "type": "function",
                                    "function": {
                                        "name": "weatherflow_delegate",
                                        "arguments": (
                                            '{"agent_id":"researcher","task":"Find sources"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    turn = await adapter(handler).complete(request())

    assert turn == DelegationTurn(agent_id="researcher", task="Find sources")


async def test_leaf_requests_do_not_expose_delegation() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        names = [tool["function"]["name"] for tool in json.loads(http_request.content)["tools"]]
        assert "weatherflow_delegate" not in names
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Leaf done"}}]},
        )

    assert await adapter(handler).complete(request(leaf=True)) == FinalTurn(content="Leaf done")


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, MiniMaxAuthenticationError), (429, MiniMaxRetryableError), (503, MiniMaxRetryableError)],
)
async def test_http_failures_are_classified_without_secret_leakage(
    status: int, error_type: type[Exception]
) -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": SECRET}})

    selected = adapter(handler)
    with pytest.raises(error_type) as captured:
        await selected.complete(request())

    assert SECRET not in str(captured.value)
    assert SECRET not in repr(selected)


async def test_unknown_functions_and_malformed_arguments_fail_closed() -> None:
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "type": "function",
                                    "function": {"name": "unknown", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "type": "function",
                                    "function": {
                                        "name": "weatherflow_delegate",
                                        "arguments": "not-json",
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
        ]
    )

    async def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    selected = adapter(handler)
    with pytest.raises(MiniMaxResponseError):
        await selected.complete(request())
    with pytest.raises(MiniMaxResponseError):
        await selected.complete(request())
