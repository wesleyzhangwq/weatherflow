import pytest

from weatherflow.extensions import (
    CredentialBroker,
    CredentialRef,
    CredentialUnavailableError,
    MappingCredentialStore,
)


async def test_credential_value_exists_only_inside_transport_callback() -> None:
    broker = CredentialBroker(MappingCredentialStore({"github.release": "super-secret-token"}))
    reference = CredentialRef(provider="github", name="release")
    observed: list[str] = []

    async def transport(secret: str) -> str:
        observed.append(secret)
        return "published"

    result = await broker.call(reference, transport)

    assert result == "published"
    assert observed == ["super-secret-token"]
    assert "super-secret-token" not in reference.model_dump_json()
    assert "super-secret-token" not in repr(broker)


async def test_missing_credential_fails_with_reference_only() -> None:
    broker = CredentialBroker(MappingCredentialStore({}))
    reference = CredentialRef(provider="calendar", name="primary")

    with pytest.raises(CredentialUnavailableError, match="calendar.primary"):
        await broker.call(reference, lambda secret: None)
