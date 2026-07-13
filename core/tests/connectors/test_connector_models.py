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


def test_registry_is_fixed_to_three_curated_read_connectors() -> None:
    assert set(CONNECTOR_DEFINITIONS) == {
        ConnectorKind.GITHUB,
        ConnectorKind.GMAIL,
        ConnectorKind.GOOGLE_CALENDAR,
    }
    assert CONNECTOR_DEFINITIONS[ConnectorKind.GITHUB].toolkit == "github"
    assert CONNECTOR_DEFINITIONS[ConnectorKind.GMAIL].read_actions == ("GMAIL_FETCH_EMAILS",)
    assert CONNECTOR_DEFINITIONS[ConnectorKind.GOOGLE_CALENDAR].read_actions == (
        "GOOGLECALENDAR_EVENTS_LIST",
    )
    assert all(definition.read_actions for definition in CONNECTOR_DEFINITIONS.values())


def test_connector_models_cannot_persist_secrets_or_connect_links() -> None:
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
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
    assert binding.granted_scopes == frozenset({"gmail:read"})

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
