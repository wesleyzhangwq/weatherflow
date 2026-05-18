from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents.dev_review_agent import DevReviewAgent
from app.config import get_settings
from app.main import create_app
from app.mcp.github import GithubConnector
from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate, DevReviewCreate


def _client() -> TestClient:
    app = create_app()
    app.state.llm = object()
    return TestClient(app)


def test_dev_review_fails_when_no_provider_configured(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()

    response = client.post("/api/dev-review/runs", json={"window_days": 7})

    assert response.status_code == 400
    assert "configure at least one provider" in response.json()["detail"].lower()

    run = dev_review_repo.get_run(1)
    assert run is not None
    assert run.status == "failed"
    assert run.error == "Configure at least one provider: GitHub or Google Calendar."
    assert dev_review_repo.latest_review() is None


def test_latest_returns_null_when_no_review_exists() -> None:
    client = _client()

    response = client.get("/api/dev-review/runs/latest")

    assert response.status_code == 200
    assert response.json() is None


def test_get_run_returns_404_when_run_has_no_review() -> None:
    run_id = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 7}))
    client = _client()

    response = client.get(f"/api/dev-review/runs/{run_id}")

    assert response.status_code == 404


def test_dev_review_persists_review_when_provider_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def fake_fetch(self, *, days: int = 7, **kwargs):
        assert days == 7
        assert kwargs == {}
        return {
            "login": "octocat",
            "events": 2,
            "by_type": {"PushEvent": 2},
            "repos_touched": 1,
            "repo_list": ["weather/app"],
        }

    async def fake_synthesize(self, window_days, contexts):
        assert window_days == 7
        assert [context.source for context in contexts] == ["github"]
        return DevReviewCreate(
            run_id=0,
            window_days=window_days,
            summary="A focused shipping week.",
            dev_weather="Shipping",
            main_work_threads=["weather/app"],
            shipping_progress=["Pushed implementation changes."],
            collaboration_load=[],
            meeting_load=[],
            rhythm_risks=[],
            next_week_suggestion="Keep the same focused cadence.",
            source_coverage={"github": {"status": "success"}},
        )

    monkeypatch.setattr(GithubConnector, "fetch", fake_fetch)
    monkeypatch.setattr(DevReviewAgent, "synthesize", fake_synthesize)

    client = _client()
    response = client.post(
        "/api/dev-review/runs",
        json={"window_days": 7, "providers": ["github"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 1
    assert body["run"]["status"] == "success"
    assert body["run"]["steps"][0]["status"] == "success"

    latest = client.get("/api/dev-review/runs/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == body["id"]


def test_dev_review_returns_400_when_configured_provider_fails(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def fake_fetch(self, *, days: int = 7, **kwargs):
        raise RuntimeError("github unavailable")

    monkeypatch.setattr(GithubConnector, "fetch", fake_fetch)

    client = _client()
    response = client.post(
        "/api/dev-review/runs",
        json={"window_days": 7, "providers": ["github"]},
    )

    assert response.status_code == 400
    assert dev_review_repo.latest_review() is None
    run = dev_review_repo.get_run(1)
    assert run is not None
    assert run.status == "failed"
    assert run.steps[0].status == "failed"


def test_dev_review_marks_run_failed_when_synthesis_raises(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def fake_fetch(self, *, days: int = 7, **kwargs):
        return {
            "login": "octocat",
            "events": 1,
            "by_type": {"PushEvent": 1},
            "repos_touched": 1,
            "repo_list": ["weather/app"],
        }

    async def fake_synthesize(self, window_days, contexts):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(GithubConnector, "fetch", fake_fetch)
    monkeypatch.setattr(DevReviewAgent, "synthesize", fake_synthesize)

    client = _client()
    response = client.post(
        "/api/dev-review/runs",
        json={"window_days": 7, "providers": ["github"]},
    )

    assert response.status_code == 500
    assert dev_review_repo.latest_review() is None
    run = dev_review_repo.get_run(1)
    assert run is not None
    assert run.status == "failed"
    assert run.error == "Dev review synthesis or persistence failed."
