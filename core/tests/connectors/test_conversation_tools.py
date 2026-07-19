from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import ToolEffect
from weatherflow.config import Settings
from weatherflow.connectors import (
    ComposioErrorCode,
    ComposioGatewayError,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
)
from weatherflow.connectors.tools import (
    COMPOSIO_RESULT_PROJECTIONS,
    COMPOSIO_TOOL_DEFINITIONS,
    _bounded_result,
    composio_tool_specs,
)
from weatherflow.extensions import CredentialRef, MappingCredentialStore
from weatherflow.runs import ToolMode
from weatherflow.runtime import AgentDefinition, FinalTurn, ToolCallTurn


class ScriptedModel:
    def __init__(self, turns: list[ToolCallTurn | FinalTurn]) -> None:
        self.turns = turns
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.turns.pop(0)


class RecordingGateway:
    def __init__(self, failure: ComposioGatewayError | None = None) -> None:
        self.calls: list[tuple[str, str, str, str, dict[str, Any]]] = []
        self.failure = failure

    async def execute_tool(
        self,
        *,
        action: str,
        version: str,
        connected_account_id: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.calls.append((action, version, connected_account_id, user_id, arguments))
        if self.failure is not None:
            raise self.failure
        if action == "GMAIL_FETCH_EMAILS":
            return {"messages": [{"subject": "Inbox review", "sender": "ops@example.com"}]}
        if action == "GOOGLECALENDAR_EVENTS_LIST":
            return {"items": [{"summary": "Planning block", "status": "confirmed"}]}
        if action in {"GITHUB_SEARCH_COMMITS", "GITHUB_LIST_COMMITS"}:
            return {
                "total_count": 1,
                "items": [
                    {
                        "sha": "abc123",
                        "html_url": "https://github.com/wesz/weatherflow/commit/abc123",
                        "commit": {"message": "Release prep"},
                    }
                ],
            }
        return {"items": [{"title": "Runtime review", "state": "open"}]}


async def connected_container(
    tmp_path: Path,
    model: ScriptedModel,
    *,
    connector: ConnectorKind = ConnectorKind.GITHUB,
    gateway: RecordingGateway | None = None,
):
    gateway = gateway or RecordingGateway()
    credentials = MappingCredentialStore(
        {
            "composio.project_api_key": "local-composio-secret",
            "provider_continuations.encryption_key_v1": "a" * 64,
        }
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path / "data"),
        model=model,
        credential_store=credentials,  # type: ignore[arg-type]
        connector_gateway=gateway,  # type: ignore[arg-type]
    )
    project = tmp_path / "project"
    project.mkdir()
    workspace = await container.authorize_workspace(name="Project", path=project)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=connector,
        external_account_id=f"ca_{connector.value}",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=connector,
        account_id=account.id,
        now=now,
    )
    await container.connector_repository.save_account(account)
    await container.connector_repository.save_binding(binding)
    return container, workspace, gateway


def test_curated_composio_tools_have_explicit_effects_and_no_generic_execute() -> None:
    specs = {tool.tool_id: tool for tool in composio_tool_specs()}

    assert "composio.execute" not in specs
    assert (
        specs["composio.github.search_issues_and_pull_requests"].effect is ToolEffect.NETWORK_READ
    )
    assert specs["composio.github.create_issue"].effect is ToolEffect.EXTERNAL_WRITE
    assert specs["composio.github.search_commits"].effect is ToolEffect.NETWORK_READ
    assert specs["composio.github.list_commits"].effect is ToolEffect.NETWORK_READ
    assert specs["composio.github.list_repositories"].effect is ToolEffect.NETWORK_READ
    assert specs["composio.gmail.send_email"].effect is ToolEffect.EXTERNAL_WRITE
    assert specs["composio.google_calendar.list_events"].effect is ToolEffect.NETWORK_READ
    assert specs["composio.google_calendar.create_event"].effect is ToolEffect.EXTERNAL_WRITE
    assert specs["composio.google_calendar.delete_event"].effect is ToolEffect.DESTRUCTIVE
    assert specs["composio.github.search_commits"].source_version == "20260713_00"
    assert specs["composio.gmail.send_email"].source_version == "20260702_01"
    assert specs["composio.google_calendar.create_event"].source_version == "20260623_00"
    assert set(specs) == {definition.tool_id for definition in COMPOSIO_TOOL_DEFINITIONS}


def test_common_oauth_tool_surface_includes_reads_and_writes_for_all_three_connectors() -> None:
    tool_ids = {definition.tool_id for definition in COMPOSIO_TOOL_DEFINITIONS}

    assert tool_ids == {
        "composio.github.get_authenticated_user",
        "composio.github.list_repositories",
        "composio.github.search_commits",
        "composio.github.list_commits",
        "composio.github.search_issues_and_pull_requests",
        "composio.github.get_pull_request",
        "composio.github.list_branches",
        "composio.github.create_issue",
        "composio.github.create_pull_request",
        "composio.gmail.fetch_emails",
        "composio.gmail.create_draft",
        "composio.gmail.send_email",
        "composio.google_calendar.list_events",
        "composio.google_calendar.find_free_slots",
        "composio.google_calendar.create_event",
        "composio.google_calendar.patch_event",
        "composio.google_calendar.delete_event",
    }


def test_every_reviewed_composio_action_has_an_output_projection() -> None:
    assert set(COMPOSIO_RESULT_PROJECTIONS) == {
        definition.action for definition in COMPOSIO_TOOL_DEFINITIONS
    }


def test_composio_tool_output_schemas_are_strict_draft_2020_12_contracts() -> None:
    for definition in COMPOSIO_TOOL_DEFINITIONS:
        schema = definition.spec().output_schema
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["properties"]
        assert schema["additionalProperties"] is False
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(_bounded_result(definition, {}))


def test_github_output_projection_keeps_useful_fields_and_drops_secrets() -> None:
    definition = next(
        item
        for item in COMPOSIO_TOOL_DEFINITIONS
        if item.action == "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS"
    )
    result = _bounded_result(
        definition,
        {
            "total_count": 1,
            "access_token": "top-level-secret",
            "text": "password=hunter2",
            "items": [
                {
                    "number": 42,
                    "title": "Runtime review",
                    "state": "open",
                    "html_url": "https://github.com/wesz/weatherflow/issues/42?token=leak",
                    "body": "Deploy with password=hunter2",
                    "user": {
                        "login": "wesz",
                        "html_url": "https://github.com/wesz?access_token=leak",
                        "secret": "nested-secret",
                    },
                }
            ],
        },
    )

    assert result["data"] == {
        "total_count": 1,
        "items": [
            {
                "number": 42,
                "title": "Runtime review",
                "state": "open",
                "html_url": "https://github.com/wesz/weatherflow/issues/42",
                "user": {"login": "wesz", "html_url": "https://github.com/wesz"},
            }
        ],
    }
    serialized = str(result)
    assert "hunter2" not in serialized
    assert "top-level-secret" not in serialized
    assert "nested-secret" not in serialized
    assert "?token=" not in serialized
    assert "?access_token=" not in serialized


def test_github_commit_projection_keeps_summary_fields_and_drops_provider_noise() -> None:
    definition = next(
        item for item in COMPOSIO_TOOL_DEFINITIONS if item.action == "GITHUB_SEARCH_COMMITS"
    )
    result = _bounded_result(
        definition,
        {
            "total_count": 1,
            "items": [
                {
                    "sha": "abc123",
                    "html_url": "https://github.com/wesz/weatherflow/commit/abc123?token=leak",
                    "commit": {
                        "message": "Release prep password=hunter2",
                        "author": {"name": "Wesz", "email": "private@example.com"},
                        "committer": {"name": "Wesz", "date": "2026-07-15T09:00:00Z"},
                        "verification": {"signature": "provider-signature"},
                    },
                    "repository": {
                        "full_name": "wesz/weatherflow",
                        "private": True,
                        "html_url": "https://github.com/wesz/weatherflow?access_token=leak",
                    },
                    "access_token": "top-level-secret",
                }
            ],
        },
    )

    assert result["data"] == {
        "total_count": 1,
        "items": [
            {
                "sha": "abc123",
                "html_url": "https://github.com/wesz/weatherflow/commit/abc123",
                "commit": {
                    "message": "Release prep password=[redacted]",
                    "author": {"name": "Wesz"},
                    "committer": {"name": "Wesz", "date": "2026-07-15T09:00:00Z"},
                },
                "repository": {
                    "full_name": "wesz/weatherflow",
                    "private": True,
                    "html_url": "https://github.com/wesz/weatherflow",
                },
            }
        ],
    }
    serialized = str(result)
    assert "hunter2" not in serialized
    assert "private@example.com" not in serialized
    assert "provider-signature" not in serialized
    assert "top-level-secret" not in serialized


def test_gmail_projection_redacts_secrets_embedded_in_reviewed_text() -> None:
    definition = next(
        item for item in COMPOSIO_TOOL_DEFINITIONS if item.action == "GMAIL_FETCH_EMAILS"
    )
    result = _bounded_result(
        definition,
        {
            "messages": [
                {
                    "id": "message-1",
                    "from": "ops@example.com",
                    "subject": "Deployment",
                    "snippet": (
                        "Use password=hunter2 and https://example.test/run?access_token=leak"
                    ),
                    "payload": {"raw": "private-body"},
                }
            ],
            "next_page_token": "opaque-provider-token",
        },
    )

    assert result["data"] == {
        "messages": [
            {
                "id": "message-1",
                "from": "ops@example.com",
                "subject": "Deployment",
                "snippet": "Use password=[redacted] and https://example.test/run",
            }
        ]
    }
    serialized = str(result)
    assert "hunter2" not in serialized
    assert "leak" not in serialized
    assert "private-body" not in serialized
    assert "opaque-provider-token" not in serialized


async def test_connected_composio_read_tool_is_frozen_and_executed_from_chat(
    tmp_path: Path,
) -> None:
    tool_id = "composio.github.search_issues_and_pull_requests"
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=tool_id, arguments={"q": "repo:wesz/weatherflow"}),
            FinalTurn(content="Found the repository activity."),
        ]
    )
    container, workspace, gateway = await connected_container(tmp_path, model)

    run, outcome = await container.submit_run(
        user_intent="Check my repository",
        workspace_id=workspace.id,
    )

    assert outcome is not None and outcome.result_summary == "Found the repository activity."
    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    assert tool_id in {tool.tool_id for tool in snapshot.tools}
    assert gateway.calls == [
        (
            "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
            "20260713_00",
            "ca_github",
            container.connector_service.installation_id,
            {
                "q": "repo:wesz/weatherflow",
                "sort": "updated",
                "order": "desc",
                "per_page": 30,
                "page": 1,
            },
        )
    ]
    assert "Runtime review" in model.requests[-1].messages[-1].content


async def test_retryable_composio_failure_reaches_model_as_typed_value_free_error(
    tmp_path: Path,
) -> None:
    tool_id = "composio.github.get_authenticated_user"
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=tool_id, arguments={}),
            FinalTurn(content="The provider is temporarily unavailable."),
        ]
    )
    gateway = RecordingGateway(ComposioGatewayError(ComposioErrorCode.UPSTREAM, retryable=True))
    container, workspace, _ = await connected_container(
        tmp_path,
        model,
        gateway=gateway,
    )

    _run, outcome = await container.submit_run(
        user_intent="Read my connected account",
        workspace_id=workspace.id,
    )

    assert outcome is not None and outcome.result_summary is not None
    observation = model.requests[-1].messages[-1].content
    assert "connector_upstream_retryable" in observation
    assert "tool_execution_failed" not in observation


@pytest.mark.parametrize(
    ("connector", "tool_id", "arguments", "expected_action", "expected_version"),
    [
        (
            ConnectorKind.GITHUB,
            "composio.github.search_commits",
            {"q": "release author:wesz"},
            "GITHUB_SEARCH_COMMITS",
            "20260713_00",
        ),
        (
            ConnectorKind.GMAIL,
            "composio.gmail.fetch_emails",
            {"query": "newer_than:7d"},
            "GMAIL_FETCH_EMAILS",
            "20260702_01",
        ),
        (
            ConnectorKind.GOOGLE_CALENDAR,
            "composio.google_calendar.list_events",
            {"timeMin": "2026-07-15T00:00:00Z", "timeMax": "2026-07-22T00:00:00Z"},
            "GOOGLECALENDAR_EVENTS_LIST",
            "20260623_00",
        ),
    ],
)
async def test_each_connected_oauth_read_surface_is_frozen_and_callable(
    tmp_path: Path,
    connector: ConnectorKind,
    tool_id: str,
    arguments: dict[str, Any],
    expected_action: str,
    expected_version: str,
) -> None:
    model = ScriptedModel(
        [ToolCallTurn(tool_id=tool_id, arguments=arguments), FinalTurn(content="Read complete.")]
    )
    container, workspace, gateway = await connected_container(tmp_path, model, connector=connector)

    run, outcome = await container.submit_run(
        user_intent="Read my connected account",
        workspace_id=workspace.id,
    )

    assert outcome is not None and outcome.result_summary == "Read complete."
    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    assert tool_id in {tool.tool_id for tool in snapshot.tools}
    assert gateway.calls[0][0] == expected_action
    assert gateway.calls[0][1] == expected_version
    assert gateway.calls[0][2] == f"ca_{connector.value}"
    assert gateway.calls[0][3] == container.connector_service.installation_id


async def test_disconnected_composio_tools_are_absent_from_new_run(tmp_path: Path) -> None:
    model = ScriptedModel([FinalTurn(content="No connected tools.")])
    credentials = MappingCredentialStore({"provider_continuations.encryption_key_v1": "a" * 64})
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path / "data"),
        model=model,
        credential_store=credentials,  # type: ignore[arg-type]
    )
    project = tmp_path / "project"
    project.mkdir()
    workspace = await container.authorize_workspace(name="Project", path=project)

    run, _ = await container.submit_run(
        user_intent="Check connections",
        workspace_id=workspace.id,
    )

    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    assert not any(tool.tool_id.startswith("composio.") for tool in snapshot.tools)


async def test_ask_mode_uses_all_connected_read_tools(
    tmp_path: Path,
) -> None:
    model = ScriptedModel([FinalTurn(content="Connection is readable.")])
    container, workspace, _ = await connected_container(tmp_path, model)

    run, _ = await container.submit_run(
        user_intent="Inspect my repositories",
        workspace_id=workspace.id,
        tool_mode=ToolMode.ASK,
    )

    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    connector_tools = tuple(tool for tool in snapshot.tools if tool.tool_id.startswith("composio."))
    assert connector_tools
    assert all(tool.effect is ToolEffect.NETWORK_READ for tool in connector_tools)
    assert "composio.github.create_issue" not in {tool.tool_id for tool in connector_tools}


async def test_bypass_mode_exposes_all_reviewed_connected_tools(tmp_path: Path) -> None:
    model = ScriptedModel([FinalTurn(content="Full reviewed surface is visible.")])
    container, workspace, _ = await connected_container(tmp_path, model)

    run, _ = await container.submit_run(
        user_intent="Prepare repository changes",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
    )

    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    connector_ids = {
        tool.tool_id for tool in snapshot.tools if tool.tool_id.startswith("composio.github.")
    }
    assert connector_ids == {
        definition.tool_id
        for definition in COMPOSIO_TOOL_DEFINITIONS
        if definition.connector is ConnectorKind.GITHUB
    }


async def test_modes_package_all_three_connector_surfaces_without_per_chat_bindings(
    tmp_path: Path,
) -> None:
    model = ScriptedModel([])
    container, workspace, _ = await connected_container(tmp_path, model)
    now = datetime.now(UTC)
    for connector in (ConnectorKind.GMAIL, ConnectorKind.GOOGLE_CALENDAR):
        account = ConnectorAccount.new(
            workspace_id=workspace.id,
            connector=connector,
            external_account_id=f"ca_{connector.value}",
            credential_ref=CredentialRef(provider="composio", name="project_api_key"),
            now=now,
        ).activate(now=now)
        binding = ConnectorBinding.new(
            workspace_id=workspace.id,
            connector=connector,
            account_id=account.id,
            now=now,
        )
        await container.connector_repository.save_account(account)
        await container.connector_repository.save_binding(binding)

    ask_run, _ = await container.submit_run(
        user_intent="Read all connected services",
        workspace_id=workspace.id,
        tool_mode=ToolMode.ASK,
        execute=False,
    )
    bypass_run, _ = await container.submit_run(
        user_intent="Use the full reviewed surface",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
        execute=False,
    )

    ask_snapshot = await container.snapshots.get_by_run_id(ask_run.id)
    bypass_snapshot = await container.snapshots.get_by_run_id(bypass_run.id)
    assert ask_snapshot is not None and bypass_snapshot is not None
    ask_tools = tuple(tool for tool in ask_snapshot.tools if tool.tool_id.startswith("composio."))
    bypass_tools = tuple(
        tool for tool in bypass_snapshot.tools if tool.tool_id.startswith("composio.")
    )
    assert len(ask_tools) == 10
    assert all(tool.effect is ToolEffect.NETWORK_READ for tool in ask_tools)
    assert len(bypass_tools) == 17
    assert {tool.effect for tool in bypass_tools} == {
        ToolEffect.NETWORK_READ,
        ToolEffect.EXTERNAL_WRITE,
        ToolEffect.DESTRUCTIVE,
    }


@pytest.mark.parametrize(
    ("connector", "tool_id", "arguments"),
    [
        (
            ConnectorKind.GITHUB,
            "composio.github.create_issue",
            {"owner": "wesz", "repo": "weatherflow", "title": "Review"},
        ),
        (
            ConnectorKind.GITHUB,
            "composio.github.create_pull_request",
            {
                "owner": "wesz",
                "repo": "weatherflow",
                "head": "fix/oauth",
                "base": "main",
                "title": "Fix OAuth tools",
            },
        ),
        (
            ConnectorKind.GMAIL,
            "composio.gmail.create_draft",
            {"recipient_email": "user@example.com", "subject": "Plan", "body": "Draft"},
        ),
        (
            ConnectorKind.GMAIL,
            "composio.gmail.send_email",
            {"recipient_email": "user@example.com", "subject": "Plan", "body": "Send"},
        ),
        (
            ConnectorKind.GOOGLE_CALENDAR,
            "composio.google_calendar.create_event",
            {
                "summary": "Planning block",
                "start_datetime": "2026-07-16T09:00:00+08:00",
                "timezone": "Asia/Shanghai",
            },
        ),
        (
            ConnectorKind.GOOGLE_CALENDAR,
            "composio.google_calendar.patch_event",
            {"event_id": "event-1", "summary": "Updated planning block"},
        ),
        (
            ConnectorKind.GOOGLE_CALENDAR,
            "composio.google_calendar.delete_event",
            {"event_id": "event-1"},
        ),
    ],
)
async def test_each_composio_write_tool_parks_for_approval_before_network(
    tmp_path: Path,
    connector: ConnectorKind,
    tool_id: str,
    arguments: dict[str, Any],
) -> None:
    model = ScriptedModel([ToolCallTurn(tool_id=tool_id, arguments=arguments)])
    container, workspace, gateway = await connected_container(tmp_path, model, connector=connector)

    run, outcome = await container.submit_run(
        user_intent="Perform an approved external write",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
    )

    assert outcome is not None and outcome.status.value == "waiting_approval"
    assert outcome.action_id is not None
    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    assert tool_id in {tool.tool_id for tool in snapshot.tools}
    assert gateway.calls == []


async def test_run_fails_closed_when_connected_account_changes_after_freeze(
    tmp_path: Path,
) -> None:
    tool_id = "composio.github.search_issues_and_pull_requests"
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=tool_id, arguments={"q": "repo:wesz/weatherflow"}),
            FinalTurn(content="The frozen connection could not be used."),
        ]
    )
    container, workspace, gateway = await connected_container(tmp_path, model)
    run, _ = await container.submit_run(
        user_intent="Check repository",
        workspace_id=workspace.id,
        execute=False,
    )
    account = await container.connector_repository.get_account(
        workspace.id,
        ConnectorKind.GITHUB,
    )
    assert account is not None
    await container.connector_repository.save_account(
        account.model_copy(update={"external_account_id": "ca_reconnected"})
    )

    outcome = await container.resume_run(run.id)

    assert outcome.result_summary == "The frozen connection could not be used."
    assert gateway.calls == []
    assert "connector account changed" in model.requests[-1].messages[-1].content


async def test_worker_inheriting_composio_read_tool_clones_parent_connector_route(
    tmp_path: Path,
) -> None:
    tool_id = "composio.github.search_issues_and_pull_requests"
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=tool_id, arguments={"q": "repo:wesz/weatherflow"}),
            FinalTurn(content="Worker found repository activity."),
        ]
    )
    container, workspace, gateway = await connected_container(tmp_path, model)
    container.workers.definitions["connector-reader"] = AgentDefinition(
        agent_id="connector-reader",
        system_prompt="Use inherited read-only connector tools.",
        is_leaf=True,
        tool_filter=frozenset({tool_id}),
    )

    parent, _ = await container.submit_run(
        user_intent="Delegate a repository inspection",
        workspace_id=workspace.id,
        execute=False,
    )
    checkpoint = await container.checkpoints.get(parent.id)
    assert checkpoint is not None
    definitions = dict(checkpoint.state["agent_definitions"])
    definitions["connector-reader"] = container.workers.definitions["connector-reader"].model_dump(
        mode="json"
    )
    async with container.database.transaction() as connection:
        await container.checkpoints.save_in(
            connection,
            checkpoint.model_copy(
                update={"state": {**checkpoint.state, "agent_definitions": definitions}}
            ),
            expected_version=checkpoint.version,
        )
    effective_workspace = workspace.model_copy(
        update={"granted_scopes": workspace.granted_scopes | {"github:read"}}
    )
    result = await container.workers.delegate(
        parent_run_id=parent.id,
        delegation_id="connector-reader-1",
        workspace=effective_workspace,
        agent_id="connector-reader",
        task="Inspect repository activity",
    )

    assert result.status == "succeeded"
    child = next(
        run
        for run in await container.runs.list_recent(workspace_id=workspace.id)
        if run.id != parent.id
    )
    snapshot = await container.snapshots.get_by_run_id(child.id)
    assert snapshot is not None
    assert {tool.tool_id for tool in snapshot.tools} == {tool_id}
    route = await container.connector_repository.get_run_route(child.id, ConnectorKind.GITHUB)
    assert route is not None
    assert route.workspace_id == workspace.id
    assert gateway.calls[0][0] == "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS"
    assert gateway.calls[0][2] == "ca_github"
