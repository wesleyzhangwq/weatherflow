from pathlib import Path

import httpx

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import KeyringCredentialStore
from weatherflow.models import MiniMaxAdapter


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password


def client() -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "MiniMax-M2.7"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_runtime_activates_and_rebuilds_persisted_minimax_adapter(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend=backend)
    settings = Settings(data_dir=tmp_path)
    first = await RuntimeContainer.create(
        settings,
        credential_store=store,
        model_http_client=client(),
    )

    configuration = await first.configure_minimax(
        api_key="valid-key",
        model="MiniMax-M2.7",
        base_url="https://api.minimax.test/v1",
    )

    assert isinstance(first.model, MiniMaxAdapter)
    assert first.loop.model is first.model
    assert first.model_configuration == configuration
    rebuilt = await RuntimeContainer.create(
        settings,
        credential_store=store,
        model_http_client=client(),
    )
    assert isinstance(rebuilt.model, MiniMaxAdapter)
    assert rebuilt.model.model == "MiniMax-M2.7"
    status = await rebuilt.model_configurations.status(rebuilt.default_workspace.id)
    assert status.configured is True
    assert status.credential_available is True
