"""Serialization helpers for MCP tool results that map to WF ProviderContext shape."""

from __future__ import annotations

from typing import Any


_REQUIRED_KEYS = {"source", "status", "window_days", "signals", "coverage", "warnings"}


def provider_context_to_dict(context: Any) -> dict[str, Any]:
    """Convert a ProviderContext (or any Pydantic model) to a plain JSON-safe dict."""
    if hasattr(context, "model_dump"):
        return context.model_dump()
    return dict(context)


def validate_mcp_tool_output(output: dict[str, Any]) -> None:
    """Assert that a raw MCP tool output dict has the required ProviderContext keys.

    Raises ValueError listing any missing keys.
    """
    missing = _REQUIRED_KEYS - set(output.keys())
    if missing:
        raise ValueError(f"MCP tool output is missing required keys: {sorted(missing)}")


__all__ = ["provider_context_to_dict", "validate_mcp_tool_output"]
