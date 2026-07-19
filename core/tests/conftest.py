from typing import Any

import pytest

import weatherflow.bootstrap as bootstrap_module
from weatherflow.activity import ActivityWatchUnavailable
from weatherflow.extensions import MappingCredentialStore


class HermeticOfflineActivityWatchClient:
    """Keep unrelated Core tests from reading the workstation's live history."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.closed = False

    @staticmethod
    def _offline() -> ActivityWatchUnavailable:
        return ActivityWatchUnavailable("ActivityWatch is offline in hermetic tests")

    async def discover(self):
        raise self._offline()

    async def info(self):
        raise self._offline()

    async def buckets(self):
        raise self._offline()

    async def events(self, *_args: object, **_kwargs: object):
        raise self._offline()

    async def settings(self) -> dict[str, Any]:
        raise self._offline()

    async def classes(self) -> list[dict[str, Any]]:
        raise self._offline()

    async def query(self, **_kwargs: object):
        raise self._offline()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def isolate_live_activitywatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bootstrap_module,
        "ActivityWatchClient",
        HermeticOfflineActivityWatchClient,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "KeyringCredentialStore",
        lambda: MappingCredentialStore({}),
    )
