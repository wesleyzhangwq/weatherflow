"""Model router + scheduler-spec parser tests."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.core.model_router import model_for
from app.core.scheduler import parse_trigger


def test_model_for_falls_back_to_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("CHAT_MODEL_STATE", raising=False)
    monkeypatch.delenv("CHAT_MODEL_REFLECTION", raising=False)
    monkeypatch.delenv("CHAT_MODEL_PLANNING", raising=False)
    monkeypatch.delenv("CHAT_MODEL_MEMORY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    assert model_for("state") == "gpt-4o-mini"
    assert model_for("reflection") == "gpt-4o-mini"
    assert model_for("planning") == "gpt-4o-mini"
    assert model_for("memory") == "gpt-4o-mini"


def test_model_for_honours_per_task_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("CHAT_MODEL_STATE", "qwen2.5:7b")
    monkeypatch.setenv("CHAT_MODEL_REFLECTION", "claude-3-5-sonnet")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    assert model_for("state") == "qwen2.5:7b"
    assert model_for("reflection") == "claude-3-5-sonnet"
    assert model_for("planning") == "gpt-4o-mini"
    assert model_for("memory") == "gpt-4o-mini"

    # restore
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_parse_trigger_daily() -> None:
    trig = parse_trigger("22:00")
    assert trig is not None
    assert "hour='22'" in repr(trig) or "hour=22" in repr(trig)


def test_parse_trigger_weekly() -> None:
    trig = parse_trigger("sun:21:00")
    assert trig is not None
    fields = {f.name: str(f) for f in trig.fields}
    assert fields["day_of_week"] == "sun"
    assert fields["hour"] == "21"
    assert fields["minute"] == "0"


def test_parse_trigger_disabled() -> None:
    assert parse_trigger("") is None
    assert parse_trigger("off") is None


def test_parse_trigger_invalid() -> None:
    with pytest.raises(ValueError):
        parse_trigger("not a cron")
