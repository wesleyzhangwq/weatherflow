from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from weatherflow.mcp.builtin_server import call_tool, tool_definitions


def test_time_server_exposes_and_executes_offline_time_tools() -> None:
    assert {tool["name"] for tool in tool_definitions("time")} == {
        "convert_time",
        "get_current_time",
    }

    current = call_tool("time", "get_current_time", {"timezone": "Asia/Shanghai"}, ())
    converted = call_tool(
        "time",
        "convert_time",
        {
            "source_timezone": "Asia/Shanghai",
            "target_timezone": "UTC",
            "time": "18:30",
        },
        (),
    )

    assert current["structuredContent"]["timezone"] == "Asia/Shanghai"
    assert converted["structuredContent"]["time"] == "10:30"


def test_git_server_allows_only_catalogued_read_operations(tmp_path: Path) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (repository / "README.md").write_text("hello\n")

    status = call_tool(
        "git-readonly",
        "git_status",
        {"repository": str(repository)},
        (repository,),
    )

    assert "README.md" in status["structuredContent"]["output"]
    with pytest.raises(ValueError, match="unsupported"):
        call_tool(
            "git-readonly",
            "git_push",
            {"repository": str(repository)},
            (repository,),
        )
    with pytest.raises(ValueError, match="authorized"):
        call_tool(
            "git-readonly",
            "git_status",
            {"repository": str(tmp_path / "outside")},
            (repository,),
        )
