import asyncio
import json
from pathlib import Path

import httpx

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import MappingCredentialStore
from weatherflow.models import ModelProvider
from weatherflow.runs import RunStatus
from weatherflow.runtime import LoopStatus


async def test_each_run_freezes_its_workspace_model_route(
    tmp_path: Path,
) -> None:
    requests: list[tuple[str, str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            models = (
                ["MiniMax-M3", "MiniMax-M2.7"]
                if request.url.host == "api.minimaxi.com"
                else ["deepseek-v4-pro"]
            )
            return httpx.Response(200, json={"data": [{"id": model} for model in models]})
        body = json.loads(request.content)
        system_message = body["messages"][0]["content"]
        requests.append((request.url.host or "", body["model"], system_message))
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"actual={request.url.host}:{body['model']}",
                        }
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    credentials = MappingCredentialStore(
        {
            "minimax.api_key": "minimax-key",
            "deepseek.api_key": "deepseek-key",
        }
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        credential_store=credentials,
        model_http_client=client,
        provider_continuation_key=bytes(range(32)),
    )
    second_root = tmp_path / "second-workspace"
    second_root.mkdir()
    second = await container.authorize_workspace(name="Second", path=second_root)

    await container.configure_model(
        workspace_id=container.default_workspace.id,
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M2.7",
        base_url="https://api.minimaxi.com/v1",
    )
    await container.configure_model(
        workspace_id=second.id,
        provider=ModelProvider.DEEPSEEK,
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
    )
    minimax_run, _ = await container.submit_run(
        user_intent="identify route",
        client_request_id="route-minimax",
        workspace_id=container.default_workspace.id,
        execute=False,
    )
    deepseek_run, _ = await container.submit_run(
        user_intent="identify route",
        client_request_id="route-deepseek",
        workspace_id=second.id,
        execute=False,
    )

    # Changing the Workspace default after acceptance must not rewrite either Run.
    await container.configure_model(
        workspace_id=container.default_workspace.id,
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M3",
        base_url="https://api.minimaxi.com/v1",
    )

    rebuilt = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        credential_store=credentials,
        model_http_client=client,
        provider_continuation_key=bytes(range(32)),
    )
    minimax_outcome, deepseek_outcome = await asyncio.gather(
        rebuilt.resume_run(minimax_run.id),
        rebuilt.resume_run(deepseek_run.id),
    )

    assert minimax_outcome.status is LoopStatus.SUCCEEDED
    assert minimax_outcome.result_summary == "actual=api.minimaxi.com:MiniMax-M2.7"
    assert deepseek_outcome.status is LoopStatus.SUCCEEDED
    assert deepseek_outcome.result_summary == "actual=api.deepseek.com:deepseek-v4-pro"
    assert sorted((host, model) for host, model, _ in requests) == [
        ("api.deepseek.com", "deepseek-v4-pro"),
        ("api.minimaxi.com", "MiniMax-M2.7"),
    ]
    assert all("runtime-selected model identity" in system for _, _, system in requests)

    minimax_route_events = await rebuilt.ledger.list_correlation(minimax_run.id, limit=100)
    route_event = next(event for event in minimax_route_events if event.type == "model.route_bound")
    assert route_event.payload == {
        "provider": "minimax",
        "model": "MiniMax-M2.7",
        "configuration_version": 0,
    }
    assert "credential" not in route_event.model_dump_json()


async def test_restart_does_not_leak_first_workspace_model_into_unconfigured_workspace(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "MiniMax-M3"}]})

    settings = Settings(data_dir=tmp_path)
    credentials = MappingCredentialStore({"minimax.api_key": "minimax-key"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    first = await RuntimeContainer.create(
        settings,
        credential_store=credentials,
        model_http_client=client,
        provider_continuation_key=bytes(range(32)),
    )
    second_root = tmp_path / "unconfigured-workspace"
    second_root.mkdir()
    second = await first.authorize_workspace(name="Unconfigured", path=second_root)
    await first.configure_model(
        workspace_id=first.default_workspace.id,
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M3",
        base_url="https://api.minimaxi.com/v1",
    )

    rebuilt = await RuntimeContainer.create(
        settings,
        credential_store=credentials,
        model_http_client=client,
        provider_continuation_key=bytes(range(32)),
    )
    run, _ = await rebuilt.submit_run(
        user_intent="stay inside this Workspace model boundary",
        client_request_id="unconfigured-workspace-route",
        workspace_id=second.id,
        execute=False,
    )

    route = await rebuilt.model_routes.get(run.id)
    assert route is not None
    assert route.workspace_id == second.id
    assert route.configuration_workspace_id is None
    assert route.provider == "echo"
    assert route.model == "echo"


async def test_run_without_a_frozen_model_route_fails_closed_to_review(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        provider_continuation_key=bytes(range(32)),
    )
    run = await container.run_coordinator.create_run(
        client_request_id="missing-model-route",
        user_intent="must not use a process-global fallback",
        workspace_id=container.default_workspace.id,
    )

    outcome = await container.resume_run(run.id)

    assert outcome.status is LoopStatus.NEEDS_REVIEW
    stored = await container.runs.get(run.id)
    assert stored is not None
    assert stored.status is RunStatus.NEEDS_REVIEW
    assert stored.error_class == "ModelRouteUnavailable"
