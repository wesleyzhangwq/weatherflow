from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents.dev_review_agent import DevReviewAgent
from app.config import get_settings
from app.main import create_app
from app.mcp.github import GithubConnector
from app.mcp.google_calendar import GoogleCalendarConnector
from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate, DevReviewCreate, ProviderContext


def _client() -> TestClient:
    app = create_app()
    app.state.llm = object()
    return TestClient(app)


def test_dev_review_fails_when_no_provider_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
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


def test_dev_review_providers_need_config_when_env_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "needs_config"
    assert providers["github"]["required_env"] == "GITHUB_TOKEN"
    assert providers["google_calendar"]["status"] == "needs_config"
    assert (
        providers["google_calendar"]["required_env"]
        == "GOOGLE_CALENDAR_TOKEN_FILE or GOOGLE_CALENDAR_ACCESS_TOKEN"
    )
    assert providers["github"]["blocking"] is False
    assert providers["google_calendar"]["blocking"] is False


def test_dev_review_providers_reports_each_ready_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "ready"
    assert providers["google_calendar"]["status"] == "needs_config"

    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "calendar-token")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "needs_config"
    assert providers["google_calendar"]["status"] == "ready"


def test_dev_review_providers_reports_calendar_ready_from_token_file(
    monkeypatch,
    tmp_path,
) -> None:
    token_file = tmp_path / "google_calendar_token.json"
    token_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(token_file))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "needs_config"
    assert providers["google_calendar"]["status"] == "ready"


def test_dev_review_providers_reports_both_ready(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "calendar-token")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "ready"
    assert providers["google_calendar"]["status"] == "ready"


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


def test_dev_review_runs_returns_recent_reviews_newest_first() -> None:
    first_run = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 7}))
    dev_review_repo.finish_run(first_run, status="success")
    first_id = dev_review_repo.create_review(
        DevReviewCreate(
            run_id=first_run,
            window_days=7,
            summary="First review.",
            dev_weather="Deep Work",
            main_work_threads=["weatherflow"],
            shipping_progress=[],
            collaboration_load=[],
            meeting_load=[],
            rhythm_risks=[],
            next_week_suggestion="Keep the focus block.",
            source_coverage={"github": {"status": "success"}},
        )
    )
    second_run = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 14}))
    dev_review_repo.finish_run(second_run, status="partial")
    second_id = dev_review_repo.create_review(
        DevReviewCreate(
            run_id=second_run,
            window_days=14,
            summary="Second review.",
            dev_weather="Shipping",
            main_work_threads=["dev review"],
            shipping_progress=["Shipped a review path."],
            collaboration_load=[],
            meeting_load=[],
            rhythm_risks=[],
            next_week_suggestion="Protect follow-up time.",
            source_coverage={
                "github": {"status": "success"},
                "google_calendar": {"status": "skipped"},
            },
        )
    )

    client = _client()
    response = client.get("/api/dev-review/runs")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [second_id, first_id]
    assert body[0]["run"]["status"] == "partial"
    assert body[0]["source_coverage"]["google_calendar"]["status"] == "skipped"


def test_dev_review_runs_respects_limit() -> None:
    for index in range(3):
        run_id = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 7}))
        dev_review_repo.finish_run(run_id, status="success")
        dev_review_repo.create_review(
            DevReviewCreate(
                run_id=run_id,
                window_days=7,
                summary=f"Review {index}.",
                dev_weather="Deep Work",
                main_work_threads=[],
                shipping_progress=[],
                collaboration_load=[],
                meeting_load=[],
                rhythm_risks=[],
                next_week_suggestion="Keep going.",
                source_coverage={"github": {"status": "success"}},
            )
        )

    client = _client()
    response = client.get("/api/dev-review/runs?limit=1")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_dev_review_persists_review_when_provider_succeeds(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
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


def test_dev_review_persists_requested_provider_coverage_when_calendar_skipped(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
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
        assert [context.source for context in contexts] == [
            "github",
            "google_calendar",
        ]
        calendar_context = contexts[1]
        assert calendar_context.status == "skipped"
        assert calendar_context.signals == {}
        assert calendar_context.warnings == [
            "Google Calendar access is not configured."
        ]
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
            source_coverage={
                context.source: {
                    "status": context.status,
                    "window_days": context.window_days,
                    "coverage": context.coverage,
                    "warnings": context.warnings,
                }
                for context in contexts
            },
        )

    monkeypatch.setattr(GithubConnector, "fetch", fake_fetch)
    monkeypatch.setattr(DevReviewAgent, "synthesize", fake_synthesize)

    client = _client()
    response = client.post(
        "/api/dev-review/runs",
        json={"window_days": 7, "providers": ["github", "google_calendar"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_coverage"]["github"]["status"] == "success"
    assert body["source_coverage"]["google_calendar"] == {
        "status": "skipped",
        "window_days": 7,
        "coverage": {"reason": "Google Calendar access is not configured."},
        "warnings": ["Google Calendar access is not configured."],
    }


def test_dev_review_uses_calendar_token_file_when_access_token_missing(
    monkeypatch,
    tmp_path,
) -> None:
    token_file = tmp_path / "google_calendar_token.json"
    token_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(token_file))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def fake_synthesize(self, window_days, contexts):
        assert window_days == 7
        assert [context.source for context in contexts] == ["google_calendar"]
        assert contexts[0].status == "success"
        return DevReviewCreate(
            run_id=0,
            window_days=window_days,
            summary="Meetings shaped the week.",
            dev_weather="Collaboration Heavy",
            main_work_threads=[],
            shipping_progress=[],
            collaboration_load=["Several calendar events were present."],
            meeting_load=["Calendar context was available."],
            rhythm_risks=[],
            next_week_suggestion="Protect a few focus blocks.",
            source_coverage={"google_calendar": {"status": "success"}},
        )

    async def fake_calendar_fetch(self, *, days: int = 7):
        assert days == 7
        assert self.access_token == ""
        assert self.token_file == str(token_file)
        return ProviderContext(
            source="google_calendar",
            status="success",
            window_days=days,
            signals={"meeting_count": 1},
            coverage={"calendar_id": "primary", "event_count": 1},
            warnings=[],
        )

    monkeypatch.setattr(GoogleCalendarConnector, "fetch", fake_calendar_fetch)
    monkeypatch.setattr(DevReviewAgent, "synthesize", fake_synthesize)

    client = _client()
    response = client.post(
        "/api/dev-review/runs",
        json={"window_days": 7, "providers": ["google_calendar"]},
    )

    assert response.status_code == 200
    assert response.json()["source_coverage"]["google_calendar"]["status"] == "success"


def test_dev_review_succeeds_with_partial_run_when_requested_provider_fails(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "configured-calendar-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def fake_github_fetch(self, *, days: int = 7, **kwargs):
        assert days == 7
        assert kwargs == {}
        return {
            "login": "octocat",
            "events": 2,
            "by_type": {"PushEvent": 2},
            "repos_touched": 1,
            "repo_list": ["weather/app"],
        }

    async def fake_calendar_fetch(self, *, days: int = 7):
        assert days == 7
        raise RuntimeError("calendar unavailable")

    async def fake_synthesize(self, window_days, contexts):
        assert window_days == 7
        assert [context.source for context in contexts] == [
            "github",
            "google_calendar",
        ]
        assert contexts[0].status == "success"
        assert contexts[1].status == "failed"
        return DevReviewCreate(
            run_id=0,
            window_days=window_days,
            summary="A focused shipping week with partial source coverage.",
            dev_weather="Shipping",
            main_work_threads=["weather/app"],
            shipping_progress=["Pushed implementation changes."],
            collaboration_load=[],
            meeting_load=[],
            rhythm_risks=["Google Calendar provider failed."],
            next_week_suggestion="Keep shipping while restoring calendar coverage.",
            source_coverage={
                context.source: {
                    "status": context.status,
                    "window_days": context.window_days,
                    "coverage": context.coverage,
                    "warnings": context.warnings,
                }
                for context in contexts
            },
        )

    monkeypatch.setattr(GithubConnector, "fetch", fake_github_fetch)
    monkeypatch.setattr(GoogleCalendarConnector, "fetch", fake_calendar_fetch)
    monkeypatch.setattr(DevReviewAgent, "synthesize", fake_synthesize)

    client = _client()
    response = client.post(
        "/api/dev-review/runs",
        json={"window_days": 7, "providers": ["github", "google_calendar"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "partial"
    assert body["source_coverage"]["github"]["status"] == "success"
    assert body["source_coverage"]["google_calendar"] == {
        "status": "failed",
        "window_days": 7,
        "coverage": {"reason": "Google Calendar provider failed."},
        "warnings": ["Google Calendar provider failed."],
    }

    persisted = dev_review_repo.get_review(body["id"])
    assert persisted is not None
    assert persisted.run.status == "partial"
    assert persisted.source_coverage["github"]["status"] == "success"
    assert persisted.source_coverage["google_calendar"]["status"] == "failed"


def test_dev_review_returns_400_when_configured_provider_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "configured-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_FILE", str(tmp_path / "missing.json"))
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
