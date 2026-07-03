"""Unified server contract — full MCP surface, in-process (no subprocess)."""

from __future__ import annotations

import asyncio

from mcp_servers.weatherflow.server import mcp
from mcp_servers.weatherflow.toolset import SPECS


def test_unified_surface_counts() -> None:
    tools = asyncio.run(mcp.list_tools())
    resources = asyncio.run(mcp.list_resources())
    prompts = asyncio.run(mcp.list_prompts())
    assert len(tools) == len(SPECS) == 15
    assert len(resources) == 4
    assert {p.name for p in prompts} == {"weekly_review", "plan_today", "rhythm_checkin"}


def test_annotations_match_three_state_taxonomy() -> None:
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for spec in SPECS:
        t = tools[spec.name]
        assert t.annotations is not None, spec.name
        mode = (t.meta or {}).get("weatherflow", {}).get("mode")
        assert mode == spec.mode, spec.name
        if mode == "read":
            assert t.annotations.readOnlyHint is True
            assert t.annotations.destructiveHint is False
        elif mode == "destructive":
            assert t.annotations.destructiveHint is True
        else:  # write
            assert t.annotations.readOnlyHint is False
            assert t.annotations.destructiveHint is False


def test_signatures_identical_to_legacy_servers() -> None:
    """Schema-drift guard: the unified server must serve byte-identical
    inputSchemas to the legacy per-domain servers (LLM routers were trained
    against those signatures)."""
    from mcp_servers.weatherflow_calendar.server import mcp as cal
    from mcp_servers.weatherflow_github.server import mcp as gh

    unified = {t.name: t.inputSchema for t in asyncio.run(mcp.list_tools())}
    for legacy in (cal, gh):
        for t in asyncio.run(legacy.list_tools()):
            assert unified[t.name] == t.inputSchema, f"schema drift on {t.name}"


def test_resources_degrade_gracefully(monkeypatch) -> None:
    """A missing store must yield an informative payload, never an exception."""
    import json

    monkeypatch.setenv("DATA_DIR", "/nonexistent/wf-overhaul-test")
    monkeypatch.setenv("MEMORY_MARKDOWN_DIR", "/nonexistent/wf-overhaul-test")

    async def read(uri: str) -> str:
        out = await mcp.read_resource(uri)
        return next(iter(out)).content

    for uri in (
        "weatherflow://profile",
        "weatherflow://events/recent",
        "weatherflow://rhythm/current",
        "weatherflow://hypotheses/active",
    ):
        body = asyncio.run(read(uri))
        payload = json.loads(body)
        assert payload.get("available") is False, uri
