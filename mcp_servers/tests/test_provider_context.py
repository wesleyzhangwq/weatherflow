from __future__ import annotations

import pytest

from mcp_servers.shared.provider_context import (
    provider_context_to_dict,
    validate_mcp_tool_output,
)


def test_validate_mcp_tool_output_passes_on_complete_dict() -> None:
    output = {
        "source": "github",
        "status": "success",
        "window_days": 7,
        "signals": {"events": 3},
        "coverage": {"repo": "weatherflow"},
        "warnings": [],
    }
    validate_mcp_tool_output(output)


def test_validate_mcp_tool_output_raises_on_missing_keys() -> None:
    output = {"source": "github", "status": "success"}
    with pytest.raises(ValueError, match="missing required keys"):
        validate_mcp_tool_output(output)


def test_validate_mcp_tool_output_lists_missing_keys() -> None:
    output = {"source": "github"}
    with pytest.raises(ValueError) as exc_info:
        validate_mcp_tool_output(output)
    msg = str(exc_info.value)
    assert "coverage" in msg
    assert "signals" in msg
    assert "warnings" in msg
    assert "window_days" in msg


def test_provider_context_to_dict_from_pydantic_model() -> None:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

    from app.memory.schemas import ProviderContext

    context = ProviderContext(
        source="github",
        status="success",
        window_days=7,
        signals={"events": 5},
        coverage={"repo": "wf"},
        warnings=[],
    )
    result = provider_context_to_dict(context)
    assert isinstance(result, dict)
    assert result["source"] == "github"
    assert result["signals"] == {"events": 5}
    for key in ("source", "status", "window_days", "signals", "coverage", "warnings"):
        assert key in result


def test_provider_context_to_dict_is_json_safe() -> None:
    import json
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

    from app.memory.schemas import ProviderContext

    context = ProviderContext(
        source="google_calendar",
        status="success",
        window_days=14,
        signals={"meeting_count": 3, "meeting_hours": 2.5},
        coverage={"calendar_id": "primary"},
        warnings=[],
    )
    result = provider_context_to_dict(context)
    json.dumps(result)
