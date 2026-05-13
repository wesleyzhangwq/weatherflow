"""Per-task model routing.

Different agents have different needs:
- State / Memory extraction: must produce strict JSON; cheaper structured model.
- Reflection / Planning: voice matters; can afford a slightly stronger model.

This router lets the user override per-task models via env without changing
agent code. If a task-specific model is unset, it falls back to ``CHAT_MODEL``.
"""

from __future__ import annotations

from typing import Literal

from app.config import Settings, get_settings

Task = Literal["state", "reflection", "planning", "memory", "default"]


def model_for(task: Task, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    overrides = {
        "state": settings.chat_model_state,
        "reflection": settings.chat_model_reflection,
        "planning": settings.chat_model_planning,
        "memory": settings.chat_model_memory,
    }
    return overrides.get(task) or settings.chat_model


__all__ = ["Task", "model_for"]
