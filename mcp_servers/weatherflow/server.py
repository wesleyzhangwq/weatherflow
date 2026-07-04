"""Unified WeatherFlow MCP server — full protocol surface, dual transport.

    python -m mcp_servers.weatherflow                     # stdio (default)
    python -m mcp_servers.weatherflow --transport http    # streamable HTTP :8765

Aggregates the legacy calendar/github toolsets (single definition point,
see toolset.py) and adds resources, prompts, and tool annotations. The
legacy per-domain entry points remain available for hosts that want a
narrower surface.
"""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from mcp_servers.weatherflow.prompts import register_prompts
from mcp_servers.weatherflow.resources import register_resources
from mcp_servers.weatherflow.toolset import SPECS, register_tools

_INSTRUCTIONS = """WeatherFlow — a developer rhythm coach exposed over MCP.

Surface: 15 tools (calendar.* + github.*), 4 read-only resources
(weatherflow://profile, events/recent, rhythm/current, hypotheses/active),
3 prompts (weekly_review, plan_today, rhythm_checkin).

Safety contract: check tool annotations. readOnlyHint tools are always safe.
Non-read tools require the server-side env gate WF_MCP_WRITE_TOOLS_ENABLED=true
AND support dry_run=true for effect preview; hosts should surface non-read
calls to the user as confirmable proposals rather than executing silently.
destructiveHint tools may overwrite or remove data — gate them hardest."""


def build_server(name: str = "weatherflow") -> FastMCP:
    mcp = FastMCP(name, instructions=_INSTRUCTIONS)
    register_tools(mcp)
    register_resources(mcp)
    register_prompts(mcp)
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Unified WeatherFlow MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio for local hosts (default); http for streamable-HTTP serving",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio


# Importable singleton — used by main(), tests, and embedding hosts.
mcp = build_server()

assert len(SPECS) == 15, "tool surface changed — update docs and this guard"

if __name__ == "__main__":
    main()
