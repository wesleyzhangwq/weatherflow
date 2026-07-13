from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import CredentialRef
from weatherflow.models import (
    ModelConfiguration,
    ModelProvider,
    ModelStatus,
    ProviderModel,
    ProviderModelCatalog,
)
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

    async def available_models(
        _service: ModelConfigurationService, provider: ModelProvider
    ) -> ProviderModelCatalog:
        assert provider is ModelProvider.DEEPSEEK
        return ProviderModelCatalog(
            provider=provider,
            models=(ProviderModel(id="deepseek-v4-flash"), ProviderModel(id="deepseek-v4-pro")),
            source="provider",
        )

    monkeypatch.setattr(RuntimeContainer, "configure_model", configure_model)
    monkeypatch.setattr(ModelConfigurationService, "status", model_status)
    monkeypatch.setattr(ModelConfigurationService, "available_models", available_models)
    transport = ASGITransport(app=create_app(settings, container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        providers = await client.get("/v1/models/providers")
        catalog = await client.get("/v1/models/providers/deepseek/models")
        response = await client.post(
            "/v1/models/configure",
            json={
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "base_url": "https://llm.example.cn/v1",
            },
        )
        openapi = await client.get("/openapi.json")

    assert providers.status_code == 200
    assert catalog.status_code == 200
    assert catalog.json() == {
        "provider": "deepseek",
        "models": [
            {
                "id": "deepseek-v4-flash",
                "selectable": True,
                "compatibility": "agent_ready",
                "note": None,
            },
            {
                "id": "deepseek-v4-pro",
                "selectable": True,
                "compatibility": "agent_ready",
                "note": None,
            },
        ],
        "source": "provider",
    }
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
    request_schema = openapi.json()["components"]["schemas"]["ModelConfigureRequest"]
    assert "api_key" not in request_schema["properties"]
    assert request_schema["additionalProperties"] is False
    assert response.json()["configuration"]["base_url"] == "https://llm.example.cn/v1"
    assert calls == [
        {
            "workspace_id": container.default_workspace.id,
            "provider": ModelProvider.DEEPSEEK,
            "model": "deepseek-v4-flash",
            "base_url": "https://llm.example.cn/v1",
        }
    ]
