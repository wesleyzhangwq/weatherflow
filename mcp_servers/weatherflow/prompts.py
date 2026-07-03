"""Parameterized MCP prompts — reusable workflows over the toolset.

A prompt is the protocol's answer to "how should an agent *use* these tools
well": the host lists them, the user picks one, the server returns a
ready-to-run instruction that names the exact tools/resources to touch.
Deep methodology lives in the corresponding skills (see ``skills/``);
prompts stay short and operational.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="weekly_review",
        description="Run a evidence-based weekly rhythm review over calendar + GitHub.",
    )
    def weekly_review(repo: str = "", days: int = 7) -> str:
        repo_clause = f"the repo `{repo}`" if repo else "the user's most active repo (via github.list_repos)"
        return (
            f"Run a weekly rhythm review over the last {days} days.\n\n"
            f"1. Read resource weatherflow://rhythm/current for the event mix and latest check-in.\n"
            f"2. Pull work signals: github.get_recent_commits and github.list_pull_requests on {repo_clause}; "
            f"calendar.search_events for the same window.\n"
            "3. Contrast plan vs. reality: meeting load vs. focus time vs. commit cadence. "
            "Cite concrete events — every claim needs a source.\n"
            "4. End with at most 3 suggestions. If one is actionable as a calendar change, "
            "propose calendar.create_focus_block — it returns a proposal for the user to confirm, "
            "never execute writes silently."
        )

    @mcp.prompt(
        name="plan_today",
        description="Plan today around existing commitments with protected focus time.",
    )
    def plan_today(focus_hours: int = 2) -> str:
        return (
            "Plan today's schedule.\n\n"
            "1. calendar.search_events for today to load commitments.\n"
            f"2. calendar.find_free_slots to locate ≥{focus_hours}h of protectable focus time.\n"
            "3. Read weatherflow://hypotheses/active — if a recent hypothesis flags overload, "
            "bias toward recovery (shorter blocks, buffers between meetings).\n"
            "4. Propose one calendar.create_focus_block for the best slot (user confirms; "
            "writes are proposals, not actions)."
        )

    @mcp.prompt(
        name="rhythm_checkin",
        description="Interpret the current rhythm snapshot and ask one good question.",
    )
    def rhythm_checkin() -> str:
        return (
            "Do a lightweight rhythm check-in.\n\n"
            "1. Read weatherflow://rhythm/current and weatherflow://profile.\n"
            "2. Summarize the week's shape in 2 sentences (evidence-linked, no vibes).\n"
            "3. Ask the user exactly one question that would most improve the picture "
            "(e.g. energy level, blockers) — then stop and wait."
        )


__all__ = ["register_prompts"]
