import json
from pathlib import Path

import httpx
import pytest

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import MappingCredentialStore
from weatherflow.models import AnthropicMessagesAdapter, ModelProvider, OpenAIResponsesAdapter
from weatherflow.runtime import LoopStatus


@pytest.mark.parametrize(
    ("provider", "model", "base_url", "credential", "adapter_type"),
    [
        (
            ModelProvider.OPENAI,
            "gpt-5.6-terra",
            "https://api.openai.com/v1",
            "openai.api_key",
            OpenAIResponsesAdapter,
        ),
        (
            ModelProvider.ANTHROPIC,
            "claude-sonnet-5",
            "https://api.anthropic.com/v1",
            "anthropic.api_key",
            AnthropicMessagesAdapter,
        ),
    ],
)
async def test_official_provider_route_survives_acceptance_and_executes_in_shared_loop(
    tmp_path: Path,
    provider: ModelProvider,
    model: str,
    base_url: str,
    credential: str,
    adapter_type: type[OpenAIResponsesAdapter] | type[AnthropicMessagesAdapter],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            if provider is ModelProvider.OPENAI:
                assert request.headers["authorization"] == "Bearer provider-key"
            else:
                assert request.headers["x-api-key"] == "provider-key"
                assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(200, json={"data": [{"id": model}]})
        body = json.loads(request.content)
        assert body["model"] == model
        if provider is ModelProvider.OPENAI:
            assert request.url.path == "/v1/responses"
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "openai done"}],
                        }
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
            )
        assert request.url.path == "/v1/messages"
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "content": [{"type": "text", "text": "anthropic done"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
        )

    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        credential_store=MappingCredentialStore({credential: "provider-key"}),
        model_http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        provider_continuation_key=bytes(range(32)),
    )
    await container.configure_model(
        workspace_id=container.default_workspace.id,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    run, _ = await container.submit_run(
        user_intent="answer through the frozen provider route",
        client_request_id=f"official-{provider.value}",
        execute=False,
    )

    route = await container.model_routes.get(run.id)
    resolved = await container.model_configurations.resolve(run.id)
    outcome = await container.resume_run(run.id)

    assert route is not None
    assert route.provider == provider.value
    assert route.model == model
    assert isinstance(resolved, adapter_type)
    assert outcome.status is LoopStatus.SUCCEEDED
    assert outcome.result_summary == f"{provider.value} done"
