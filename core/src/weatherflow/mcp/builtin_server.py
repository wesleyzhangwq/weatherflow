from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}~^:+-]{0,199}$")


def tool_definitions(preset: str) -> tuple[dict[str, Any], ...]:
    if preset == "time":
        return (
            _tool(
                "get_current_time",
                "Read the current time in one IANA timezone.",
                {
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                    "required": ["timezone"],
                    "additionalProperties": False,
                },
            ),
            _tool(
                "convert_time",
                "Convert a local HH:MM time between IANA timezones.",
                {
                    "type": "object",
                    "properties": {
                        "source_timezone": {"type": "string"},
                        "target_timezone": {"type": "string"},
                        "time": {"type": "string", "pattern": r"^\d{2}:\d{2}$"},
                    },
                    "required": ["source_timezone", "target_timezone", "time"],
                    "additionalProperties": False,
                },
            ),
        )
    if preset == "git-readonly":
        repository = {"type": "string", "description": "Authorized repository path"}
        path = {"type": "string", "description": "Optional repository-relative path"}
        return (
            _git_tool("git_status", "Read repository status.", {"repository": repository}),
            _git_tool(
                "git_diff_unstaged",
                "Read unstaged changes.",
                {"repository": repository, "path": path},
            ),
            _git_tool(
                "git_diff_staged",
                "Read staged changes.",
                {"repository": repository, "path": path},
            ),
            _git_tool(
                "git_diff",
                "Read changes against one revision.",
                {
                    "repository": repository,
                    "target": {"type": "string"},
                    "path": path,
                },
            ),
            _git_tool(
                "git_log",
                "Read recent commit history.",
                {
                    "repository": repository,
                    "max_count": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            ),
            _git_tool(
                "git_show",
                "Read one commit or object.",
                {"repository": repository, "revision": {"type": "string"}},
            ),
            _git_tool("git_branch", "List local and remote branches.", {"repository": repository}),
        )
    raise ValueError("unsupported builtin MCP preset")


def call_tool(
    preset: str,
    name: str,
    arguments: dict[str, Any],
    roots: tuple[Path, ...],
) -> dict[str, Any]:
    allowed = {tool["name"] for tool in tool_definitions(preset)}
    if name not in allowed:
        raise ValueError("unsupported builtin MCP tool")
    if preset == "time":
        output = _call_time(name, arguments)
    elif preset == "git-readonly":
        output = _call_git(name, arguments, roots)
    else:
        raise ValueError("unsupported builtin MCP preset")
    text = json.dumps(output, ensure_ascii=False, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": output,
    }


def serve_stdio(preset: str, roots: tuple[Path, ...]) -> int:
    authorized_roots = tuple(path.expanduser().resolve() for path in roots)
    for line in sys.stdin.buffer:
        request: object = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                continue
            request_id = request.get("id")
            if request_id is None:
                continue
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": f"weatherflow-{preset}", "version": "3.0.0"},
                }
            elif method == "tools/list":
                result = {"tools": list(tool_definitions(preset))}
            elif method == "tools/call":
                params = request.get("params")
                if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                    raise ValueError("invalid tools/call request")
                arguments = params.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ValueError("invalid tool arguments")
                result = call_tool(preset, params["name"], arguments, authorized_roots)
            elif method == "ping":
                result = {}
            else:
                raise ValueError("unsupported MCP method")
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32602, "message": "builtin MCP request rejected"},
            }
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


def _tool(name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
        "outputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def _git_tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return _tool(
        name,
        description,
        {
            "type": "object",
            "properties": properties,
            "required": ["repository"],
            "additionalProperties": False,
        },
    )


def _timezone(value: Any) -> ZoneInfo:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError("invalid timezone")
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("unknown timezone") from error


def _call_time(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_current_time":
        zone = _timezone(arguments.get("timezone"))
        current = datetime.now(zone)
        return {
            "timezone": zone.key,
            "datetime": current.isoformat(timespec="seconds"),
            "utc_offset": current.strftime("%z"),
        }
    source = _timezone(arguments.get("source_timezone"))
    target = _timezone(arguments.get("target_timezone"))
    value = arguments.get("time")
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("invalid local time")
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("invalid local time")
    source_time = datetime.now(source).replace(hour=hour, minute=minute, second=0, microsecond=0)
    converted = source_time.astimezone(target)
    return {
        "source_timezone": source.key,
        "target_timezone": target.key,
        "time": converted.strftime("%H:%M"),
        "datetime": converted.isoformat(timespec="seconds"),
    }


def _call_git(
    name: str,
    arguments: dict[str, Any],
    roots: tuple[Path, ...],
) -> dict[str, Any]:
    repository = _authorized_repository(arguments.get("repository"), roots)
    path = _relative_path(arguments.get("path"))
    if name == "git_status":
        command = ("status", "--short", "--branch")
    elif name == "git_diff_unstaged":
        command = ("diff", "--", *path)
    elif name == "git_diff_staged":
        command = ("diff", "--cached", "--", *path)
    elif name == "git_diff":
        target = _revision(arguments.get("target", "HEAD"))
        command = ("diff", target, "--", *path)
    elif name == "git_log":
        maximum = arguments.get("max_count", 20)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 100:
            raise ValueError("invalid max_count")
        command = ("log", f"--max-count={maximum}", "--oneline", "--decorate")
    elif name == "git_show":
        command = ("show", "--stat", "--oneline", _revision(arguments.get("revision")))
    elif name == "git_branch":
        command = ("branch", "--all", "--no-color")
    else:
        raise ValueError("unsupported builtin MCP tool")
    result = subprocess.run(
        ("/usr/bin/git", "--no-optional-locks", "-C", str(repository), *command),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PATH": "/usr/bin:/bin",
        },
    )
    if result.returncode != 0:
        raise ValueError("git read operation failed")
    return {"repository": str(repository), "output": result.stdout[:100_000]}


def _authorized_repository(value: Any, roots: tuple[Path, ...]) -> Path:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise ValueError("invalid repository")
    repository = Path(value).expanduser().resolve()
    if not any(repository == root or repository.is_relative_to(root) for root in roots):
        raise ValueError("repository is outside authorized roots")
    if not repository.is_dir():
        raise ValueError("repository is outside authorized roots")
    return repository


def _relative_path(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if not isinstance(value, str) or len(value) > 4_096:
        raise ValueError("invalid repository path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("invalid repository path")
    return (str(path),)


def _revision(value: Any) -> str:
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        raise ValueError("invalid revision")
    return value
