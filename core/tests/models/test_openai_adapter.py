import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.continuations import ProviderContinuation
from weatherflow.extensions import CredentialBroker, CredentialRef, MappingCredentialStore
from weatherflow.models import (
    ModelResponseFailureStage,
    OpenAIAuthenticationError,
    OpenAIResponseError,
    OpenAIResponsesAdapter,
    OpenAIRetryableError,
)
from weatherflow.runtime import (
    AgentDefinition,
    AgentMessage,
    FinalTurn,
    MessageRole,
    ModelCompletion,
    ModelRequest,
    ToolCallTurn,
)

SECRET = "openai-secret-never-persist"


@pytest.mark.parametrize(
    ("response", "expected_stage"),
    [
        (httpx.Response(400, json={}), ModelResponseFailureStage.HTTP_RESPONSE),
        (httpx.Response(200, json={"output": []}), ModelResponseFailureStage.CHOICE),
        (
            httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "unknown",
                            "name": "not_registered",
                            "arguments": "{}",
                        }
                    ]
                },
            ),
            ModelResponseFailureStage.MESSAGE,
        ),
        (
            httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "   "}],
                        }
                    ]
                },
            ),
            ModelResponseFailureStage.EMPTY_TEXT,
        ),
    ],
)
async def test_openai_response_errors_expose_only_a_bounded_failure_stage(
    response: httpx.Response,
    expected_stage: ModelResponseFailureStage,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(OpenAIResponseError) as caught:
        await adapter(handler).complete(request())

    assert caught.value.stage is expected_stage


def request(
    *messages: AgentMessage,
    continuations: tuple[ProviderContinuation, ...] = (),
    tool_free: bool = False,
) -> ModelRequest:
    return ModelRequest(
        run_id="run-openai",
        agent=AgentDefinition(
            agent_id="orchestrator",
            system_prompt="Stay inside the frozen WeatherFlow authority boundary.",
        ),
        messages=messages or (AgentMessage(role=MessageRole.USER, content="Read README.md"),),
        tools=()
        if tool_free
        else (
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
        tool_free=tool_free,
    )


def adapter(handler) -> OpenAIResponsesAdapter:
    return OpenAIResponsesAdapter(
        broker=CredentialBroker(MappingCredentialStore({"openai.api_key": SECRET})),
        credential_ref=CredentialRef(provider="openai", name="api_key"),
        model="gpt-5.6-terra",
        base_url="https://api.openai.test/v1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_responses_text_tools_usage_and_provider_continuation_round_trip() -> None:
    provider_output: list[dict] = []

    async def first_handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url == "https://api.openai.test/v1/responses"
        assert http_request.headers["authorization"] == f"Bearer {SECRET}"
        body = json.loads(http_request.content)
        assert body["model"] == "gpt-5.6-terra"
        assert body["store"] is False
        assert body["include"] == ["reasoning.encrypted_content"]
        assert body["instructions"].startswith("Stay inside the frozen")
        assert body["input"] == [{"role": "user", "content": "Read README.md"}]
        read_tool = next(
            tool for tool in body["tools"] if tool["description"] == "Read a scoped file"
        )
        assert read_tool["type"] == "function"
        # Frozen ToolSpecs are validated by WeatherFlow after the model turn;
        # schemas that are not provider-strict-compatible must remain usable.
        assert read_tool["strict"] is False
        provider_output.extend(
            [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "encrypted_content": "opaque-provider-reasoning",
                },
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call-openai",
                    "name": read_tool["name"],
                    "arguments": '{"path":"README.md"}',
                },
            ]
        )
        return httpx.Response(
            200,
            json={
                "output": provider_output,
                "usage": {"input_tokens": 21, "output_tokens": 7},
            },
        )

    first = await adapter(first_handler).complete(request())

    assert isinstance(first, ModelCompletion)
    assert first.turn == ToolCallTurn(
        call_id="call-openai",
        tool_id="developer.read_file",
        arguments={"path": "README.md"},
        usage={"input_tokens": 21, "output_tokens": 7},
    )
    assert first.continuation is not None
    assert first.continuation.provider == "openai"
    assert first.continuation.payload == {"role": "assistant", "output": provider_output}

    assistant = AgentMessage(
        role=MessageRole.ASSISTANT,
        content=json.dumps(first.turn.model_dump(mode="json")),
    )
    observation = AgentMessage(
        role=MessageRole.TOOL,
        name="developer.read_file",
        tool_call_id="call-openai",
        content='{"content":"WeatherFlow"}',
    )
    now = datetime(2026, 7, 14, tzinfo=UTC)
    continuation = ProviderContinuation(
        run_id="run-openai",
        step_index=1,
        provider="openai",
        model="gpt-5.6-terra",
        payload={"role": "assistant", "output": provider_output},
        created_at=now,
        expires_at=now + timedelta(days=7),
    )

    async def second_handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert body["input"][1:3] == provider_output
        assert body["input"][3] == {
            "type": "function_call_output",
            "call_id": "call-openai",
            "output": '{"content":"WeatherFlow"}',
        }
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "完成"}],
                    }
                ],
                "usage": {"input_tokens": 32, "output_tokens": 4},
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
        usage={"input_tokens": 32, "output_tokens": 4},
    )


async def test_restricted_tool_free_turn_reconstructs_safe_function_history() -> None:
    assistant = AgentMessage(
        role=MessageRole.ASSISTANT,
        content=json.dumps(
            {
                "kind": "tool_call",
                "call_id": "call-activity",
                "tool_id": "activity.query_range",
                "arguments": {"start": "2026-07-17T00:00:00+08:00"},
            }
        ),
    )
    observation = AgentMessage(
        role=MessageRole.TOOL,
        name="activity.query_range",
        tool_call_id="call-activity",
        content='{"application_seconds":{"Codex":7200}}',
    )

    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert "tools" not in body
        assert "tool_choice" not in body
        assert body["input"][-2]["type"] == "function_call"
        assert body["input"][-2]["call_id"] == "call-activity"
        assert body["input"][-2]["name"].startswith("wf_activity_query_range_")
        assert body["input"][-1] == {
            "type": "function_call_output",
            "call_id": "call-activity",
            "output": '{"application_seconds":{"Codex":7200}}',
        }
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "完成"}],
                    }
                ]
            },
        )

    final = await adapter(handler).complete(
        request(
            AgentMessage(role=MessageRole.USER, content="总结最近活动"),
            assistant,
            observation,
            tool_free=True,
        )
    )

    assert final == FinalTurn(content="完成")


async def test_openai_lists_models_and_classifies_http_failures_without_secret() -> None:
    async def models_handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/v1/models"
        assert http_request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(200, json={"data": [{"id": "gpt-5.6-terra"}]})

    selected = adapter(models_handler)
    assert await selected.list_models() == ("gpt-5.6-terra",)

    async def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": SECRET}})

    with pytest.raises(OpenAIAuthenticationError) as caught:
        await adapter(unauthorized).complete(request())
    assert SECRET not in str(caught.value)

    async def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": SECRET}})

    with pytest.raises(OpenAIRetryableError):
        await adapter(unavailable).complete(request())


async def test_openai_rejects_unknown_function_calls() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "unknown",
                        "name": "not_registered",
                        "arguments": "{}",
                    }
                ]
            },
        )

    with pytest.raises(OpenAIResponseError):
        await adapter(handler).complete(request())
