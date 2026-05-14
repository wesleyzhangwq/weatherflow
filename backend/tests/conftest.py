"""Test fixtures.

We give every test a fresh on-disk SQLite file so FTS5 / triggers behave
exactly like production.
"""

from __future__ import annotations

import os
import tempfile
from typing import List, Sequence

import pytest

from app.config import get_settings
from app.memory.store import init_db, set_db_path


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch: pytest.MonkeyPatch) -> None:
    tmpdir = tempfile.mkdtemp(prefix="wf-test-")
    db_path = os.path.join(tmpdir, "weatherflow.db")
    set_db_path(db_path)
    monkeypatch.setenv("DATA_DIR", tmpdir)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    init_db(db_path)
    yield
    set_db_path(None)  # type: ignore[arg-type]
    get_settings.cache_clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
class FakeLLM:
    """Deterministic LLM stub. Returns whatever the test programs."""

    def __init__(self) -> None:
        self.chat_responses: list[str] = []
        self.embed_dim = 8
        self.calls: list[tuple[str, Sequence]] = []

    def queue_chat(self, *responses: str) -> None:
        self.chat_responses.extend(responses)

    async def chat(self, messages, **_kwargs) -> str:
        self.calls.append(("chat", list(messages)))
        if not self.chat_responses:
            raise RuntimeError("no chat response queued")
        return self.chat_responses.pop(0)

    async def embed(self, texts, **_kwargs) -> List[List[float]]:
        self.calls.append(("embed", list(texts)))
        return [[float((i + 1) / (self.embed_dim + 1))] * self.embed_dim for i, _ in enumerate(texts)]

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
