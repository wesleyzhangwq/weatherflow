import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import EchoModelAdapter, RuntimeContainer
from weatherflow.config import Settings
from weatherflow.runtime import FinalTurn
from weatherflow.sessions import ConversationSession
from weatherflow.workspaces import Workspace


class GatedModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request):
        self.started.set()
        await self.release.wait()
        return FinalTurn(content="Background result")


class GatedFollowUpModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.started.set()
            await self.release.wait()
            return FinalTurn(content="First result")
        return FinalTurn(content="Revised result")


async def test_run_api_is_idempotent_and_exposes_timeline(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=EchoModelAdapter())
    app = create_app(container=container)
    transport = ASGITransport(app=app)
    payload = {
        "client_request_id": "request-1",
        "user_intent": "Explain WeatherFlow",
        "workspace_id": container.default_workspace.id,
        "execute": True,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/v1/runs", json=payload)
        repeated = await client.post("/v1/runs", json=payload)
        run_id = first.json()["id"]
        fetched = await client.get(f"/v1/runs/{run_id}")
        timeline = await client.get(f"/v1/runs/{run_id}/timeline")

    assert first.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == run_id
    assert fetched.json()["status"] == "succeeded"
    assert container.automation_scheduler.running is False
    event_types = [event["type"] for event in timeline.json()]
    assert event_types[0] == "run.created"
    assert "run.result_committed" in event_types


async def test_run_api_returns_typed_not_found(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/runs/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "run_not_found", "run_id": "missing"}}


async def test_desktop_run_acknowledges_before_background_model_completion(
    tmp_path: Path,
) -> None:
    model = GatedModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "background-1",
                "user_intent": "Inspect safely",
                "workspace_id": container.default_workspace.id,
            },
        )
        assert response.status_code == 201
        await asyncio.wait_for(model.started.wait(), timeout=1)
        stored = await container.runs.get(response.json()["id"])
        assert stored is not None and stored.status.value in {"planning", "running"}
        model.release.set()
        completed = await container.wait_for_background_run(stored.id, timeout_seconds=1)

    assert completed.status.value == "succeeded"
    final = await container.runs.get(stored.id)
    assert final is not None and final.result_summary == "Background result"


async def test_run_list_is_scoped_to_workspace(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    workspace_id = container.default_workspace.id
    await container.submit_run(
        user_intent="Queued",
        client_request_id="list-1",
        workspace_id=workspace_id,
        execute=False,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/runs", params={"workspace_id": workspace_id})
        await container.wait_for_background_run(response.json()[0]["id"], timeout_seconds=1)

    assert response.status_code == 200
    assert [run["client_request_id"] for run in response.json()] == ["list-1"]


async def test_api_rejects_invalid_pagination_before_repository_execution(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run_limit = await client.get("/v1/runs", params={"limit": 0})
        session_limit = await client.get(
            "/v1/sessions",
            params={"workspace_id": container.default_workspace.id, "limit": 1001},
        )
        history_limit = await client.get(
            "/v1/automations/missing/history",
            params={"limit": 0},
        )

    assert run_limit.status_code == 422
    assert session_limit.status_code == 422
    assert history_limit.status_code == 422


async def test_run_api_rejects_blank_or_oversized_intent(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    base = {"workspace_id": container.default_workspace.id}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blank = await client.post("/v1/runs", json={**base, "user_intent": "   "})
        oversized = await client.post(
            "/v1/runs",
            json={**base, "user_intent": "x" * 20_001},
        )

    assert blank.status_code == 422
    assert oversized.status_code == 422


async def test_run_api_reports_missing_context_run_without_mislabeling_workspace(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/runs",
            json={
                "user_intent": "Follow up safely",
                "workspace_id": container.default_workspace.id,
                "context_run_id": "missing-context",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "context_run_not_found",
            "context_run_id": "missing-context",
        }
    }


async def test_follow_up_run_keeps_durable_context_link(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=EchoModelAdapter())
    source, _ = await container.submit_run(
        user_intent="Produce a first result",
        client_request_id="source-run",
    )
    follow_up, _ = await container.submit_run(
        user_intent="Now make it more concise",
        client_request_id="follow-up-run",
        context_run_id=source.id,
        execute=False,
    )

    checkpoint = await container.checkpoints.get(follow_up.id)
    timeline = await container.ledger.list_correlation(follow_up.id, limit=1000)

    assert checkpoint is not None
    assert checkpoint.transcript[0].role.value == "system"
    assert source.id in checkpoint.transcript[0].content
    assert [message.role.value for message in checkpoint.transcript] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert checkpoint.transcript[1].content == "Produce a first result"
    assert checkpoint.transcript[2].content == "Echo: Produce a first result"
    assert checkpoint.transcript[-1].content == "Now make it more concise"
    link = [event for event in timeline if event.type == "run.follow_up_linked"]
    assert len(link) == 1
    assert link[0].payload["context_run_id"] == source.id


async def test_cancel_stops_daemon_owned_background_run(tmp_path: Path) -> None:
    model = GatedModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "cancel-background",
                "user_intent": "Wait for cancellation",
                "workspace_id": container.default_workspace.id,
            },
        )
        await asyncio.wait_for(model.started.wait(), timeout=1)
        cancelled = await client.post(f"/v1/runs/{accepted.json()['id']}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert container.background_tasks == {}


async def test_run_control_api_durably_follows_up_at_final_boundary(tmp_path: Path) -> None:
    model = GatedFollowUpModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "live-follow-up",
                "user_intent": "Draft the result",
                "workspace_id": container.default_workspace.id,
            },
        )
        run_id = accepted.json()["id"]
        await asyncio.wait_for(model.started.wait(), timeout=1)
        queued = await client.post(
            f"/v1/runs/{run_id}/controls",
            json={"kind": "follow_up", "content": "Make it concise."},
        )
        model.release.set()
        completed = await container.wait_for_background_run(run_id, timeout_seconds=1)
        rejected = await client.post(
            f"/v1/runs/{run_id}/controls",
            json={"kind": "steer", "content": "Too late"},
        )

    assert queued.status_code == 202
    assert queued.json()["kind"] == "follow_up"
    assert queued.json()["status"] == "pending"
    assert completed.result_summary == "Revised result"
    assert len(model.requests) == 2
    assert [message.content for message in model.requests[1].messages[-2:]] == [
        "First result",
        "Make it concise.",
    ]
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == {
        "code": "run_control_rejected",
        "status": "succeeded",
    }


async def test_conversation_sessions_can_be_created_renamed_pinned_and_listed(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    workspace_id = container.default_workspace.id

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/sessions",
            json={"workspace_id": workspace_id, "title": "Release notes"},
        )
        session_id = created.json()["id"]
        run = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "session-api-run",
                "user_intent": "Review the release",
                "workspace_id": workspace_id,
                "session_id": session_id,
                "execute": True,
            },
        )
        updated = await client.patch(
            f"/v1/sessions/{session_id}",
            params={"workspace_id": workspace_id},
            json={"title": "Pinned release", "pinned": True},
        )
        listed = await client.get("/v1/sessions", params={"workspace_id": workspace_id})
        session_runs = await client.get(
            "/v1/runs",
            params={"workspace_id": workspace_id, "session_id": session_id},
        )

    assert created.status_code == 201
    assert run.status_code == 201
    assert run.json()["session_id"] == session_id
    assert updated.status_code == 200
    assert updated.json()["title"] == "Pinned release"
    assert updated.json()["pinned"] is True
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == session_id
    assert listed.json()[0]["latest_run_id"] == run.json()["id"]
    assert [item["id"] for item in session_runs.json()] == [run.json()["id"]]


async def test_session_endpoints_fail_closed_across_workspace_boundaries(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    owner_workspace_id = container.default_workspace.id
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_workspace = Workspace.new(
        name="Other",
        action_roots=[other_root],
        internal_root=tmp_path / "other-internal",
        artifact_root=tmp_path / "other-artifacts",
    )
    await container.workspaces.create(other_workspace)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/sessions",
            json={"workspace_id": owner_workspace_id, "title": "Private session"},
        )
        session_id = created.json()["id"]
        run = await container.run_coordinator.create_run(
            user_intent="Private task",
            client_request_id="private-session-run",
            workspace_id=owner_workspace_id,
            session_id=session_id,
        )

        cross_workspace_patch = await client.patch(
            f"/v1/sessions/{session_id}",
            params={"workspace_id": other_workspace.id},
            json={"title": "Stolen"},
        )
        cross_workspace_list = await client.get(
            "/v1/runs",
            params={"workspace_id": other_workspace.id, "session_id": session_id},
        )
        unscoped_session_list = await client.get(
            "/v1/runs",
            params={"session_id": session_id},
        )

    assert run.workspace_id == owner_workspace_id
    assert cross_workspace_patch.status_code == 404
    assert cross_workspace_patch.json()["detail"]["code"] == "session_not_found"
    assert cross_workspace_list.status_code == 404
    assert cross_workspace_list.json()["detail"]["code"] == "session_not_found"
    assert unscoped_session_list.status_code == 422


async def test_delete_session_removes_runs_events_and_unreferenced_artifact_bytes(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    workspace = container.default_workspace
    session = ConversationSession.new(
        workspace_id=workspace.id,
        title="Delete this conversation",
    )
    await container.sessions.create(session)
    run = await container.run_coordinator.create_run(
        client_request_id="delete-session-api",
        user_intent="Sensitive conversation",
        workspace_id=workspace.id,
        session_id=session.id,
    )
    artifact = await container.artifact_store.put_bytes(
        run_id=run.id,
        workspace=workspace,
        name="private.txt",
        media_type="text/plain",
        data=b"private",
    )
    artifact_path = Path(workspace.artifact_root) / artifact.relative_path
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        deleted = await client.delete(
            f"/v1/sessions/{session.id}",
            params={"workspace_id": workspace.id},
        )
        listed = await client.get("/v1/sessions", params={"workspace_id": workspace.id})
        run_response = await client.get(f"/v1/runs/{run.id}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert session.id not in {item["id"] for item in listed.json()}
    assert run_response.status_code == 404
    assert await container.ledger.list_correlation(run.id) == []
    assert artifact_path.exists() is False


async def test_delete_session_requires_owning_workspace(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    owner_workspace = container.default_workspace
    session = ConversationSession.new(
        workspace_id=owner_workspace.id,
        title="Private session",
    )
    await container.sessions.create(session)
    other_root = tmp_path / "other-delete"
    other_root.mkdir()
    other_workspace = Workspace.new(
        name="Other delete",
        action_roots=[other_root],
        internal_root=tmp_path / "other-delete-internal",
        artifact_root=tmp_path / "other-delete-artifacts",
    )
    await container.workspaces.create(other_workspace)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_workspace = await client.delete(f"/v1/sessions/{session.id}")
        cross_workspace = await client.delete(
            f"/v1/sessions/{session.id}",
            params={"workspace_id": other_workspace.id},
        )

    assert missing_workspace.status_code == 422
    assert cross_workspace.status_code == 404
    assert cross_workspace.json()["detail"]["code"] == "session_not_found"
    assert await container.sessions.get(session.id) is not None


async def test_delete_session_keeps_content_addressed_blob_until_last_owner_is_deleted(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    workspace = container.default_workspace
    first_session = ConversationSession.new(workspace_id=workspace.id, title="First")
    second_session = ConversationSession.new(workspace_id=workspace.id, title="Second")
    await container.sessions.create(first_session)
    await container.sessions.create(second_session)
    first_run = await container.run_coordinator.create_run(
        client_request_id="shared-blob-first",
        user_intent="First owner",
        workspace_id=workspace.id,
        session_id=first_session.id,
    )
    second_run = await container.run_coordinator.create_run(
        client_request_id="shared-blob-second",
        user_intent="Second owner",
        workspace_id=workspace.id,
        session_id=second_session.id,
    )
    first_artifact = await container.artifact_store.put_bytes(
        run_id=first_run.id,
        workspace=workspace,
        name="first.txt",
        media_type="text/plain",
        data=b"shared",
    )
    second_artifact = await container.artifact_store.put_bytes(
        run_id=second_run.id,
        workspace=workspace,
        name="second.txt",
        media_type="text/plain",
        data=b"shared",
    )
    artifact_path = Path(workspace.artifact_root) / first_artifact.relative_path
    assert second_artifact.relative_path == first_artifact.relative_path
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first_deleted = await client.delete(
            f"/v1/sessions/{first_session.id}",
            params={"workspace_id": workspace.id},
        )
        assert artifact_path.exists() is True
        second_deleted = await client.delete(
            f"/v1/sessions/{second_session.id}",
            params={"workspace_id": workspace.id},
        )

    assert first_deleted.status_code == 204
    assert second_deleted.status_code == 204
    assert artifact_path.exists() is False


async def test_client_request_id_cannot_return_a_run_from_another_workspace(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    owner_workspace_id = container.default_workspace.id
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_workspace = Workspace.new(
        name="Other",
        action_roots=[other_root],
        internal_root=tmp_path / "other-internal",
        artifact_root=tmp_path / "other-artifacts",
    )
    await container.workspaces.create(other_workspace)
    first = await container.run_coordinator.create_run(
        client_request_id="workspace-bound-request",
        user_intent="Owner task",
        workspace_id=owner_workspace_id,
    )
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "workspace-bound-request",
                "user_intent": "Other task",
                "workspace_id": other_workspace.id,
            },
        )

    assert first.workspace_id == owner_workspace_id
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "client_request_conflict"
    await container.close()
