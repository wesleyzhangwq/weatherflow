from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


async def test_status_metrics_export_and_reset_require_explicit_requests(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    container = await RuntimeContainer.create(settings)
    transport = ASGITransport(app=create_app(settings, container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/v1/system/status")
        metrics = await client.get("/v1/diagnostics/metrics")
        export = await client.post("/v1/diagnostics/export")
        preview = await client.get("/v1/privacy/reset/behavior")
        rejected = await client.post("/v1/privacy/reset/behavior", json={"confirm": False})
        accepted = await client.post("/v1/privacy/reset/behavior", json={"confirm": True})

    assert status.status_code == 200
    assert status.json()["local_only"] is True
    assert status.json()["telemetry_upload"] is False
    assert status.json()["behavior_sensor"]["raw_content_captured"] is False
    assert metrics.status_code == 200
    assert export.status_code == 201
    assert Path(export.json()["path"]).is_relative_to(
        Path(container.default_workspace.internal_root)
    )
    assert preview.json()["category"] == "behavior"
    assert rejected.status_code == 409
    assert accepted.status_code == 200


async def test_security_scan_endpoint_reports_only_metadata(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    container = await RuntimeContainer.create(settings)
    transport = ASGITransport(app=create_app(settings, container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/security/scan")

    assert response.status_code == 200
    assert response.json() == {"findings": []}
