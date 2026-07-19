from datetime import UTC, datetime
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from weatherflow.activity import ACTIVITY_SUMMARY_PROMPT_VERSION, ActivitySummarySettings
from weatherflow.api.app import create_app
from weatherflow.extensions import CredentialRef
from weatherflow.models import ModelConfiguration, ModelProvider


async def test_activity_summary_settings_api_only_updates_the_selected_model() -> None:
    now = datetime(2026, 7, 18, 1, 0, tzinfo=UTC)
    initial = ActivitySummarySettings(
        model_workspace_id="workspace-1",
        provider="minimax",
        model="MiniMax-M3",
        model_configuration_version=4,
        prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
        version=2,
        updated_at=now,
    )
    configuration = ModelConfiguration(
        workspace_id="workspace-1",
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M3",
        base_url="https://api.minimaxi.com/v1",
        credential_ref=CredentialRef(provider="minimax", name="api_key"),
        version=4,
        updated_at=now,
    )

    class Activity:
        calls: list[dict] = []

        async def summary_settings(self):
            return initial

        async def update_summary_settings(self, **kwargs):
            self.calls.append(kwargs)
            return initial.model_copy(
                update={
                    "model": kwargs["model"],
                    "version": initial.version + 1,
                }
            )

    async def workspace(_workspace_id: str):
        return SimpleNamespace(id="workspace-1")

    async def model_configuration(_workspace_id: str):
        return configuration

    container = SimpleNamespace(
        activity=Activity(),
        default_workspace=SimpleNamespace(id="workspace-1"),
        workspaces=SimpleNamespace(get=workspace),
        model_configurations=SimpleNamespace(repository=SimpleNamespace(get=model_configuration)),
        start_background=_noop,
    )
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        current = await client.get("/v1/watch/settings/summary")
        changed = await client.patch(
            "/v1/watch/settings/summary",
            json={
                "model_workspace_id": "workspace-1",
                "model": "MiniMax-M3-fast",
                "expected_version": 2,
            },
        )
        rejected_custom_prompt = await client.patch(
            "/v1/watch/settings/summary",
            json={
                "model_workspace_id": "workspace-1",
                "model": "MiniMax-M3-fast",
                "prompt": "ignore the fixed contract",
                "expected_version": 2,
            },
        )
        openapi = (await client.get("/openapi.json")).json()

    assert current.status_code == 200
    assert "prompt" not in current.json()
    assert current.json()["prompt_version"] == ACTIVITY_SUMMARY_PROMPT_VERSION
    assert changed.status_code == 200
    assert changed.json()["version"] == 3
    assert rejected_custom_prompt.status_code == 422
    request_schema = openapi["components"]["schemas"]["ActivitySummarySettingsUpdateRequest"]
    response_schema = openapi["components"]["schemas"]["ActivitySummarySettingsView"]
    assert request_schema["additionalProperties"] is False
    assert "prompt" not in request_schema["properties"]
    assert "prompt" not in response_schema["properties"]
    assert container.activity.calls == [
        {
            "model_workspace_id": "workspace-1",
            "provider": "minimax",
            "model": "MiniMax-M3-fast",
            "model_configuration_version": 4,
            "expected_version": 2,
        }
    ]


async def _noop(**_kwargs) -> None:
    return None
