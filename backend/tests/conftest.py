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
    # Tests must never inherit real observability credentials from the
    # developer's .env — a configured Langfuse client spawns background
    # ingestion threads that hammer the (absent) host and spam stderr.
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    # Point Qdrant at a dead port: with the dev Qdrant running, semantic
    # recall/projection would otherwise hit the REAL vector store — tests
    # would pollute it and read each other's (and the developer's) memories.
    # The semantic layer degrades to [] on connection failure by contract.
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")
    config.get_settings.cache_clear()

    event_log.set_db_path(str(db_path))
    event_log.init_db(str(db_path))

    # The process-wide mem0 Memory cache must not leak across tests — a cached
    # real client would bypass per-test monkeypatching of Memory.from_config.
    from app.memory.semantic import mem0_config

    mem0_config._MEMORY_CACHE.clear()

    # sse-starlette pins its module-global shutdown Event to the first event
    # loop that touches it; every later TestClient (fresh loop) then dies with
    # "bound to a different event loop". Reset it per test.
    try:
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
    except ImportError:
        pass

    yield tmp_dir

    mem0_config._MEMORY_CACHE.clear()
    event_log.set_db_path(None)  # type: ignore[arg-type]
    config.get_settings.cache_clear()
    shutil.rmtree(tmp_dir, ignore_errors=True)


class StubLLM:
    """LLM stub that returns canned responses.

    ``responses`` feeds ``chat`` (plan / hypothesis JSON / synthesize);
    ``raw_responses`` feeds ``chat_raw`` (graph act node — full message dicts
    with optional ``tool_calls``).
    """

    def __init__(self, responses: list[str] | None = None, raw_responses: list[dict] | None = None):
        self._responses = list(responses or [])
        self._raw_responses = list(raw_responses or [])
        self.calls: list[dict] = []

    async def chat(self, messages, *, model=None, temperature=0.4, max_tokens=None, response_format=None, disable_thinking=False):
        self.calls.append({"messages": list(messages), "response_format": response_format, "disable_thinking": disable_thinking})
        if not self._responses:
            raise AssertionError("StubLLM out of responses")
        return self._responses.pop(0)

    async def chat_raw(
        self, messages, *, model=None, temperature=0.4, max_tokens=None,
        tools=None, tool_choice=None, response_format=None,
    ):
        if not self._raw_responses:
            raise AssertionError("StubLLM out of raw_responses")
        return self._raw_responses.pop(0)

    async def chat_raw_stream(
        self, messages, *, on_delta, model=None, temperature=0.4,
        max_tokens=None, tools=None, tool_choice=None,
    ):
        # Mirror the real client's contract: deltas for visible content, then
        # the assembled message — so graph tests cover the streaming path.
        msg = await self.chat_raw(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, tools=tools, tool_choice=tool_choice,
        )
        if msg.get("content"):
            on_delta(msg["content"])
        return msg

    async def embed(self, texts, *, model=None):
        return [[0.0] * 4 for _ in texts]

    async def aclose(self):
        return None


@pytest.fixture
def stub_llm_factory():
    def make(responses: list[str]) -> StubLLM:
        return StubLLM(responses)
    return make
