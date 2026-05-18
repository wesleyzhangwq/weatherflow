from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate


def test_dev_review_fails_when_no_provider_configured(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = TestClient(create_app())

    response = client.post("/api/dev-review/runs", json={"window_days": 7})

    assert response.status_code == 400
    assert "configure at least one provider" in response.json()["detail"].lower()

    run = dev_review_repo.get_run(1)
    assert run is not None
    assert run.status == "failed"
    assert run.error == "Configure at least one provider: GitHub or Google Calendar."
    assert dev_review_repo.latest_review() is None


def test_latest_returns_null_when_no_review_exists() -> None:
    client = TestClient(create_app())

    response = client.get("/api/dev-review/runs/latest")

    assert response.status_code == 200
    assert response.json() is None


def test_get_run_returns_404_when_run_has_no_review() -> None:
    run_id = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 7}))
    client = TestClient(create_app())

    response = client.get(f"/api/dev-review/runs/{run_id}")

    assert response.status_code == 404
