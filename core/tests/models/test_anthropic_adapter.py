import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.continuations import ProviderContinuation
from weatherflow.extensions import CredentialBroker, CredentialRef, MappingCredentialStore
from weatherflow.models import (
    AnthropicAuthenticationError,
    AnthropicMessagesAdapter,
    AnthropicResponseError,
    AnthropicRetryableError,
)
from weatherflow.runtime import (
    AgentDefinition,
    AgentMessage,
    FinalTurn,
    MessageRole,
    ModelCompletion,
    ModelRequest,
    ToolCallBatchTurn,
    ToolCallTurn,
)

SECRET = "anthropic-secret-never-persist"


def request(
    *messages: AgentMessage,
    continuations: tuple[ProviderContinuation, ...] = (),
) -> ModelRequest:
    return ModelRequest(
        run_id="run-anthropic",
        agent=AgentDefinition(
            agent_id="orchestrator",
            system_prompt="Stay inside the frozen WeatherFlow authority boundary.",
        ),
        messages=messages or (AgentMessage(role=MessageRole.USER, content="Read README.md"),),
        tools=(
            ToolSpec(
                tool_id="developer.read_file",
                description="Read a scoped file",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
                output_schema={"type": "object"},
                effect=ToolEffect.OBSERVE,
                source="builtin.developer",
                source_version="1",
            ),
        ),
        provider_continuations=continuations,
    )


def adapter(handler) -> AnthropicMessagesAdapter:
    return AnthropicMessagesAdapter(
        broker=CredentialBroker(MappingCredentialStore({"anthropic.api_key": SECRET})),
        credential_ref=CredentialRef(provider="anthropic", name="api_key"),
        model="claude-sonnet-5",
        base_url="https://api.anthropic.test/v1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_messages_text_tools_usage_and_provider_continuation_round_trip() -> None:
    provider_content: list[dict] = []

    async def first_handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url == "https://api.anthropic.test/v1/messages"
        assert http_request.headers["x-api-key"] == SECRET
        assert http_request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(http_request.content)
        assert body["model"] == "claude-sonnet-5"
        assert body["system"].startswith("Stay inside the frozen")
        assert body["messages"] == [{"role": "user", "content": "Read README.md"}]
        read_tool = next(
            tool for tool in body["tools"] if tool["description"] == "Read a scoped file"
        )
        # Frozen ToolSpecs are validated by WeatherFlow after the model turn;
        # schemas that are not provider-strict-compatible must remain usable.
        assert read_tool["strict"] is False
        provider_content.extend(
            [
                {
                    "type": "thinking",
                    "thinking": "provider-private-reasoning",
                    "signature": "opaque-signature",
                },
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": read_tool["name"],
                    "input": {"path": "README.md"},
                },
            ]
        )
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "content": provider_content,
                "stop_reason": "tool_use",
                "usage": {
                    "input_tokens": 20,
                    "cache_creation_input_tokens": 3,
                    "cache_read_input_tokens": 2,
                    "output_tokens": 8,
                },
            },
        )

    first = await adapter(first_handler).complete(request())

    assert isinstance(first, ModelCompletion)
    assert first.turn == ToolCallTurn(
        call_id="toolu_1",
        tool_id="developer.read_file",
        arguments={"path": "README.md"},
        usage={"input_tokens": 25, "output_tokens": 8},
    )
    assert first.continuation is not None
    assert first.continuation.provider == "anthropic"
    assert first.continuation.payload == {"role": "assistant", "content": provider_content}

    assistant = AgentMessage(
        role=MessageRole.ASSISTANT,
        content=json.dumps(first.turn.model_dump(mode="json")),
    )
    observation = AgentMessage(
        role=MessageRole.TOOL,
        name="developer.read_file",
        tool_call_id="toolu_1",
        content='{"content":"WeatherFlow"}',
    )
    now = datetime(2026, 7, 14, tzinfo=UTC)
    continuation = ProviderContinuation(
        run_id="run-anthropic",
        step_index=1,
        provider="anthropic",
        model="claude-sonnet-5",
        payload={"role": "assistant", "content": provider_content},
        created_at=now,
        expires_at=now + timedelta(days=7),
    )

    async def second_handler(http_request: httpx.Request) -> httpx.Response:
        messages = json.loads(http_request.content)["messages"]
        assert messages[1] == {"role": "assistant", "content": provider_content}
        assert messages[2] == {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": '{"content":"WeatherFlow"}',
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "content": [{"type": "text", "text": "完成"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 30, "output_tokens": 4},
            },
        )

    final = await adapter(second_handler).complete(
        request(
            AgentMessage(role=MessageRole.USER, content="Read README.md"),
            assistant,
            observation,
            continuations=(continuation,),
        )
    )

    assert final == FinalTurn(
        content="完成",
        usage={"input_tokens": 30, "output_tokens": 4},
    )


async def test_anthropic_lists_models_and_classifies_http_failures_without_secret() -> None:
    async def models_handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/v1/models"
        assert http_request.url.params["limit"] == "1000"
        assert http_request.headers["x-api-key"] == SECRET
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

    assert await adapter(models_handler).list_models() == ("claude-sonnet-5",)

    async def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": SECRET}})

    with pytest.raises(AnthropicAuthenticationError) as caught:
        await adapter(unauthorized).complete(request())
    assert SECRET not in str(caught.value)

    async def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(529, json={"error": {"message": SECRET}})

    with pytest.raises(AnthropicRetryableError):
        await adapter(unavailable).complete(request())


async def test_anthropic_rejects_unknown_tool_use() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_x", "name": "unknown", "input": {}}],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    with pytest.raises(AnthropicResponseError):
        await adapter(handler).complete(request())


async def test_parallel_tool_results_are_returned_in_one_anthropic_user_turn() -> None:
    provider_content: list[dict] = []

    async def first_handler(http_request: httpx.Request) -> httpx.Response:
        read_tool = next(
            tool
            for tool in json.loads(http_request.content)["tools"]
            if tool["description"] == "Read a scoped file"
        )
        provider_content.extend(
            [
                {
                    "type": "tool_use",
                    "id": "toolu_a",
                    "name": read_tool["name"],
                    "input": {"path": "A.md"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_b",
                    "name": read_tool["name"],
                    "input": {"path": "B.md"},
                },
            ]
        )
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "content": provider_content,
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 2, "output_tokens": 2},
            },
        )

    first = await adapter(first_handler).complete(request())
    assert isinstance(first, ModelCompletion)
    assert isinstance(first.turn, ToolCallBatchTurn)

    now = datetime(2026, 7, 14, tzinfo=UTC)
    continuation = ProviderContinuation(
        run_id="run-anthropic",
        step_index=1,
        provider="anthropic",
        model="claude-sonnet-5",
        payload={"role": "assistant", "content": provider_content},
        created_at=now,
        expires_at=now + timedelta(days=7),
    )

    async def second_handler(http_request: httpx.Request) -> httpx.Response:
        messages = json.loads(http_request.content)["messages"]
        assert messages[2] == {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_a", "content": "A"},
                {"type": "tool_result", "tool_use_id": "toolu_b", "content": "B"},
            ],
        }
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 1},
            },
        )

    final = await adapter(second_handler).complete(
        request(
            AgentMessage(role=MessageRole.USER, content="Read both"),
            AgentMessage(
                role=MessageRole.ASSISTANT,
                content=json.dumps(first.turn.model_dump(mode="json")),
            ),
            AgentMessage(
                role=MessageRole.TOOL,
                name="developer.read_file",
                tool_call_id="toolu_a",
                content="A",
            ),
            AgentMessage(
                role=MessageRole.TOOL,
                name="developer.read_file",
                tool_call_id="toolu_b",
                content="B",
            ),
            continuations=(continuation,),
        )
    )
    assert final == FinalTurn(content="done", usage={"input_tokens": 4, "output_tokens": 1})
