"""Protocol-first registry discovery — pure-logic contract (no subprocess)."""

from __future__ import annotations

from app.mcp_client.tool_registry import (
    Tool,
    ToolRegistry,
    _mode_from_annotations,
    registry,
    set_registry,
)


def test_mode_mapping_from_annotations():
    assert _mode_from_annotations({"readOnlyHint": True}) == "read"
    assert _mode_from_annotations({"readOnlyHint": False, "destructiveHint": True}) == "destructive"
    assert _mode_from_annotations({"readOnlyHint": False, "destructiveHint": False}) == "write"
    # Unknown mutation profile -> most conservative gated bucket, never "read".
    assert _mode_from_annotations(None) == "write"


def test_discovered_destructive_tools_never_register():
    reg = ToolRegistry()
    reg.register(Tool("calendar.delete_event", "destructive", "", {}, "calendar"))
    reg.register(Tool("calendar.search_events", "read", "", {}, "calendar"))
    assert reg.get("calendar.delete_event") is None
    assert reg.get("calendar.search_events") is not None


def test_set_registry_swaps_process_singleton():
    original = registry()
    try:
        fresh = ToolRegistry()
        fresh.register(Tool("github.list_repos", "read", "", {}, "github"))
        set_registry(fresh)
        assert [t.name for t in registry().list_tools()] == ["github.list_repos"]
    finally:
        set_registry(original)
