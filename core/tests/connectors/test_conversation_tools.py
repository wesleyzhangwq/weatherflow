from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import ToolEffect
from weatherflow.config import Settings
from weatherflow.connectors import (
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConversationAccess,
)
from weatherflow.connectors.tools import (
    COMPOSIO_RESULT_PROJECTIONS,
    COMPOSIO_TOOL_DEFINITIONS,
    _bounded_result,
    composio_tool_specs,
)
from weatherflow.extensions import CredentialRef, MappingCredentialStore
from weatherflow.runtime import AgentDefinition, FinalTurn, ToolCallTurn


class ScriptedModel:
    def __init__(self, turns: list[ToolCallTurn | FinalTurn]) -> None:
        self.turns = turns
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.turns.pop(0)


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def execute_tool(
        self,
        *,
        action: str,
        version: str,
        connected_account_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.calls.append((action, version, connected_account_id, arguments))
        return {"items": [{"title": "Runtime review", "state": "open"}]}


async def connected_container(tmp_path: Path, model: ScriptedModel):
    gateway = RecordingGateway()
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
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_github",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    ).with_conversation_access(
        ConversationAccess.READ,
        tool_ids=frozenset(
            definition.tool_id
            for definition in COMPOSIO_TOOL_DEFINITIONS
            if definition.connector is ConnectorKind.GITHUB
            and definition.effect is ToolEffect.NETWORK_READ
        ),
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
    assert specs["composio.gmail.send_email"].effect is ToolEffect.EXTERNAL_WRITE
    assert specs["composio.google_calendar.list_events"].effect is ToolEffect.NETWORK_READ
    assert set(specs) == {definition.tool_id for definition in COMPOSIO_TOOL_DEFINITIONS}


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
            "20260703_00",
            "ca_github",
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


async def test_connected_but_conversation_disabled_keeps_tools_out_of_run(
    tmp_path: Path,
) -> None:
    model = ScriptedModel([FinalTurn(content="Connection remains private.")])
    container, workspace, _ = await connected_container(tmp_path, model)
    binding = await container.connector_repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    await container.connector_repository.save_binding(
        binding.with_conversation_access(
            ConversationAccess.DISABLED,
            tool_ids=frozenset(),
        )
    )

    run, _ = await container.submit_run(
        user_intent="Do not use my connection",
        workspace_id=workspace.id,
    )

    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    assert not any(tool.tool_id.startswith("composio.") for tool in snapshot.tools)


async def test_composio_write_tool_parks_for_approval_before_network(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            ToolCallTurn(
                tool_id="composio.github.create_issue",
                arguments={"owner": "wesz", "repo": "weatherflow", "title": "Review"},
            )
        ]
    )
    container, workspace, gateway = await connected_container(tmp_path, model)
    binding = await container.connector_repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    await container.connector_repository.save_binding(
        binding.with_conversation_access(
            ConversationAccess.READ_WRITE,
            tool_ids=frozenset(
                definition.tool_id
                for definition in COMPOSIO_TOOL_DEFINITIONS
                if definition.connector is ConnectorKind.GITHUB
            ),
        )
    )

    _, outcome = await container.submit_run(
        user_intent="Create a review issue",
        workspace_id=workspace.id,
    )

    assert outcome is not None and outcome.status.value == "waiting_approval"
    assert outcome.action_id is not None
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
