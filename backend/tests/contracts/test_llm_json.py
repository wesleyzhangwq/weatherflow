"""chat_json hardening for reasoning models (MiniMax-M3 thinking control)."""

from __future__ import annotations


import pytest

from app.config import Settings
from app.core.llm import _strip_to_json, chat_json


def test_supports_thinking_param_auto_detects_minimax(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_CONTROL", "auto")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.minimaxi.com/v1")
    assert Settings().supports_thinking_param is True

    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    assert Settings().supports_thinking_param is False


def test_supports_thinking_param_force_on_off(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_THINKING_CONTROL", "on")
    assert Settings().supports_thinking_param is True
    monkeypatch.setenv("LLM_THINKING_CONTROL", "off")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.minimaxi.com/v1")
    assert Settings().supports_thinking_param is False


def test_strip_to_json_handles_unterminated_think():
    # Truncated reasoning: a stray <think> with no closing tag, no JSON yet.
    assert _strip_to_json("<think>reasoning was cut off") == ""
    # Complete think block before the JSON is removed.
    assert _strip_to_json('<think>x</think>\n{"a":1}') == '{"a":1}'


class _StubLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, *, model=None, temperature=0.4, max_tokens=None,
                   response_format=None, disable_thinking=False):
        self.calls.append({"max_tokens": max_tokens, "disable_thinking": disable_thinking})
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_chat_json_disables_thinking_and_floors_tokens():
    stub = _StubLLM(['{"ok": true}'])
    out = await chat_json(stub, [{"role": "user", "content": "x"}])
    assert out == {"ok": True}
    assert stub.calls[0]["disable_thinking"] is True
    assert stub.calls[0]["max_tokens"] >= 4096  # floored


@pytest.mark.asyncio
async def test_chat_json_retries_once_on_truncation():
    # First response is truncated JSON → JSONDecodeError → retry with 2x tokens.
    stub = _StubLLM(['{"a": "unterminated', '{"a": "ok"}'])
    out = await chat_json(stub, [{"role": "user", "content": "x"}])
    assert out == {"a": "ok"}
    assert len(stub.calls) == 2
    assert stub.calls[1]["max_tokens"] == stub.calls[0]["max_tokens"] * 2
