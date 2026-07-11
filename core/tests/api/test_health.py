from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.config import Settings


def test_settings_use_weatherflow_environment_prefix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WF_HOST", "127.0.0.2")
    monkeypatch.setenv("WF_PORT", "9876")
    monkeypatch.setenv("WF_DATA_DIR", str(tmp_path))

    settings = Settings()

    assert settings.host == "127.0.0.2"
    assert settings.port == 9876
    assert settings.data_dir == tmp_path


async def test_health_returns_typed_core_identity(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    transport = ASGITransport(app=create_app(settings))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "weatherflow-core",
        "version": "3.0.0a1",
    }
