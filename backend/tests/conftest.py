"""Shared fixtures: isolated DB + profile dir per test."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from app import config
from app.memory import event_log


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch) -> Iterator[Path]:
    """Each test gets a fresh sqlite DB + profile dir."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="wf-test-"))
    db_path = tmp_dir / "wf.db"
    profile_dir = tmp_dir / "profile"
    profile_dir.mkdir(exist_ok=True)

    monkeypatch.setenv("DATA_DIR", str(tmp_dir))
    monkeypatch.setenv("MEMORY_MARKDOWN_DIR", str(profile_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config.get_settings.cache_clear()

    event_log.set_db_path(str(db_path))
    event_log.init_db(str(db_path))

    yield tmp_dir

    event_log.set_db_path(None)  # type: ignore[arg-type]
    config.get_settings.cache_clear()
    shutil.rmtree(tmp_dir, ignore_errors=True)


class StubLLM:
    """LLM stub that returns canned responses based on a list."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, *, model=None, temperature=0.4, max_tokens=None, response_format=None):
        self.calls.append({"messages": list(messages), "response_format": response_format})
        if not self._responses:
            raise AssertionError("StubLLM out of responses")
        return self._responses.pop(0)

    async def embed(self, texts, *, model=None):
        return [[0.0] * 4 for _ in texts]

    async def aclose(self):
        return None


@pytest.fixture
def stub_llm_factory():
    def make(responses: list[str]) -> StubLLM:
        return StubLLM(responses)
    return make
