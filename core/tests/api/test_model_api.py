from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import CredentialRef
from weatherflow.models import ModelConfiguration, ModelProvider, ModelStatus
from weatherflow.models.configuration import ModelConfigurationService


async def test_provider_catalog_and_generic_configuration_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path)
    container = await RuntimeContainer.create(settings)
    configured = ModelConfiguration(
        workspace_id=container.default_workspace.id,
        provider=ModelProvider.DEEPSEEK,
        model="deepseek-v4-flash",
        base_url="https://llm.example.cn/v1",
        credential_ref=CredentialRef(provider="deepseek", name="api_key"),
        updated_at=datetime.now(UTC),
    )
    calls: list[dict[str, object]] = []

    async def configure_model(_container: RuntimeContainer, **kwargs: object) -> ModelConfiguration:
        calls.append(kwargs)
        return configured

    async def model_status(_service: ModelConfigurationService, _workspace_id: str) -> ModelStatus:
        return ModelStatus(
            configured=True,
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://llm.example.cn/v1",
            credential_available=True,
        )

    monkeypatch.setattr(RuntimeContainer, "configure_model", configure_model)
    monkeypatch.setattr(ModelConfigurationService, "status", model_status)
    transport = ASGITransport(app=create_app(settings, container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        providers = await client.get("/v1/models/providers")
        response = await client.post(
            "/v1/models/configure",
            json={
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "base_url": "https://llm.example.cn/v1",
                "api_key": "never-return-this",
            },
        )

    assert providers.status_code == 200
    assert {item["provider"] for item in providers.json()["providers"]} == {
        "minimax",
        "deepseek",
        "moonshot",
        "qwen",
        "zhipu",
        "siliconflow",
        "stepfun",
    }
    assert response.status_code == 200
    assert response.json()["configuration"]["base_url"] == "https://llm.example.cn/v1"
    assert "never-return-this" not in response.text
    assert calls == [
        {
            "workspace_id": container.default_workspace.id,
            "provider": ModelProvider.DEEPSEEK,
            "api_key": "never-return-this",
            "model": "deepseek-v4-flash",
            "base_url": "https://llm.example.cn/v1",
        }
    ]
