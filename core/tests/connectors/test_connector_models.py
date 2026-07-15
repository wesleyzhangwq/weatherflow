from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from weatherflow.connectors import (
    CONNECTOR_DEFINITIONS,
    ConnectionPhase,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorSnapshot,
    SourceItem,
)
from weatherflow.extensions import CredentialRef


def test_registry_exposes_twenty_curated_oauth_connectors_without_virtual_tools() -> None:
    assert len(CONNECTOR_DEFINITIONS) == 20
    assert set(CONNECTOR_DEFINITIONS) == set(ConnectorKind)
    assert CONNECTOR_DEFINITIONS[ConnectorKind.GITHUB].toolkit == "github"
    assert CONNECTOR_DEFINITIONS[ConnectorKind.GMAIL].read_actions == ("GMAIL_FETCH_EMAILS",)
    assert CONNECTOR_DEFINITIONS[ConnectorKind.GOOGLE_CALENDAR].read_actions == (
        "GOOGLECALENDAR_EVENTS_LIST",
    )
    assert {
        definition.connector
        for definition in CONNECTOR_DEFINITIONS.values()
        if definition.auto_fetch_supported
    } == {
        ConnectorKind.GITHUB,
        ConnectorKind.GMAIL,
        ConnectorKind.GOOGLE_CALENDAR,
    }
    assert {
        definition.connector
        for definition in CONNECTOR_DEFINITIONS.values()
        if definition.conversation_tools_supported
    } == {
        ConnectorKind.GITHUB,
        ConnectorKind.GMAIL,
        ConnectorKind.GOOGLE_CALENDAR,
    }
    assert all(definition.category for definition in CONNECTOR_DEFINITIONS.values())
    assert all(definition.toolkit for definition in CONNECTOR_DEFINITIONS.values())
    assert all(
        not definition.read_actions
        for definition in CONNECTOR_DEFINITIONS.values()
        if not definition.auto_fetch_supported
    )
    expected_catalog_auth_actions = {
        ConnectorKind.SLACK: ("SLACK_SEARCH_MESSAGES",),
        ConnectorKind.NOTION: ("NOTION_SEARCH_NOTION_PAGE",),
        ConnectorKind.GOOGLE_DRIVE: ("GOOGLEDRIVE_FIND_FILE",),
        ConnectorKind.GOOGLE_SHEETS: ("GOOGLESHEETS_VALUES_GET",),
        ConnectorKind.OUTLOOK: ("OUTLOOK_QUERY_EMAILS",),
        ConnectorKind.ONE_DRIVE: ("ONE_DRIVE_ONEDRIVE_FIND_FILE",),
        ConnectorKind.MICROSOFT_TEAMS: ("MICROSOFT_TEAMS_SEARCH_MESSAGES",),
        ConnectorKind.LINEAR: ("LINEAR_SEARCH_ISSUES",),
        ConnectorKind.JIRA: ("JIRA_GET_ISSUE",),
        ConnectorKind.CONFLUENCE: ("CONFLUENCE_CQL_SEARCH",),
        ConnectorKind.DROPBOX: ("DROPBOX_FILES_SEARCH",),
        ConnectorKind.GITLAB: ("GITLAB_GET_PROJECT",),
        ConnectorKind.DISCORD: ("DISCORD_LIST_MY_GUILDS",),
        ConnectorKind.TRELLO: (),
        ConnectorKind.ASANA: ("ASANA_SEARCH_TASKS_IN_WORKSPACE",),
        ConnectorKind.AIRTABLE: ("AIRTABLE_LIST_RECORDS",),
        ConnectorKind.CLICKUP: ("CLICKUP_GET_TASKS",),
    }
    assert {
        connector: CONNECTOR_DEFINITIONS[connector].reviewed_auth_actions
        for connector in expected_catalog_auth_actions
    } == expected_catalog_auth_actions
    assert all(
        definition.reviewed_auth_actions
        for definition in CONNECTOR_DEFINITIONS.values()
        if definition.connector is not ConnectorKind.TRELLO
    )


def test_connector_models_cannot_persist_secrets_or_connect_links() -> None:
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id="workspace-1",
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_github",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    )

    serialized = account.model_dump_json()

    assert "api_key" in serialized
    assert "secret" not in ConnectorAccount.model_fields
    assert "connect_url" not in ConnectorAccount.model_fields
    assert account.phase is ConnectionPhase.WAITING_USER
    assert account.activate(now=now).phase is ConnectionPhase.ACTIVE


def test_binding_interval_and_snapshot_size_are_bounded() -> None:
    binding = ConnectorBinding.new(
        workspace_id="workspace-1",
        connector=ConnectorKind.GMAIL,
        account_id="account-1",
        now=datetime.now(UTC),
    )
    assert binding.interval_minutes == 60
    assert binding.granted_scopes == frozenset({"gmail:read", "gmail:write"})
    assert "conversation_access" not in ConnectorBinding.model_fields
    assert "conversation_tool_ids" not in ConnectorBinding.model_fields

    with pytest.raises(ValidationError):
        binding.model_copy(update={"interval_minutes": 1}, deep=True).__class__.model_validate(
            {**binding.model_dump(), "interval_minutes": 1}
        )

    items = tuple(
        SourceItem(
            source_id=f"mail-{index}",
            occurred_at=datetime.now(UTC),
            title="Title",
            summary="Summary",
        )
        for index in range(101)
    )
    with pytest.raises(ValidationError):
        ConnectorSnapshot(
            workspace_id="workspace-1",
            connector=ConnectorKind.GMAIL,
            fetched_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            items=items,
        )
