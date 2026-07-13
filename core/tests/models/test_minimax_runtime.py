from pathlib import Path

import httpx

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import CredentialRef, KeyringCredentialStore
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
        return httpx.Response(200, json={"data": [{"id": "MiniMax-M3"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_runtime_activates_and_rebuilds_persisted_minimax_adapter(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend=backend)
    store.set(CredentialRef(provider="minimax", name="api_key"), "valid-key")
    settings = Settings(data_dir=tmp_path)
    first = await RuntimeContainer.create(
        settings,
        credential_store=store,
        model_http_client=client(),
    )

    configuration = await first.configure_minimax(
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1",
    )

    assert first.model_configuration == configuration
    run, _ = await first.submit_run(
        user_intent="hello",
        client_request_id="frozen-model-route",
        execute=False,
    )
    route = await first.model_routes.get(run.id)
    resolved = await first.model_configurations.resolve(run.id)
    assert route is not None
    assert route.provider == "minimax"
    assert route.model == "MiniMax-M3"
    assert isinstance(resolved, MiniMaxAdapter)
    assert resolved.model == "MiniMax-M3"
    rebuilt = await RuntimeContainer.create(
        settings,
        credential_store=store,
        model_http_client=client(),
    )
    rebuilt_route = await rebuilt.model_routes.get(run.id)
    rebuilt_adapter = await rebuilt.model_configurations.resolve(run.id)
    assert rebuilt_route == route
    assert isinstance(rebuilt_adapter, MiniMaxAdapter)
    assert rebuilt_adapter.model == "MiniMax-M3"
    status = await rebuilt.model_configurations.status(rebuilt.default_workspace.id)
    assert status.configured is True
    assert status.credential_available is True
