"""Tests for multi-repo GitHub MCP aggregation."""

from __future__ import annotations

import pytest

from app.providers.github_mcp import _aggregate_repo_result


def test_aggregate_repo_result_single_repo():
    """Test aggregating a single repo result."""
    all_repos: list[str] = []
    event_type_counts: dict[str, int] = {}
    all_coverage: dict[str, dict] = {}

    status = {
        "repo": "owner1/repo1",
        "open_issues_count": 5,
        "open_prs_count": 3,
        "recent_activity": [],
    }
    commits = {"commits": [{"sha": "abc"}, {"sha": "def"}]}

    _aggregate_repo_result(
        "owner1",
        "repo1",
        status,
        commits,
        all_repos,
        event_type_counts,
        all_coverage,
    )

    assert all_repos == ["owner1/repo1"]
    assert event_type_counts == {"Commit": 2, "Issue": 5, "PullRequest": 3}
    assert all_coverage["owner1/repo1"] == {
        "commit_count": 2,
        "open_issues_count": 5,
        "open_prs_count": 3,
    }


def test_aggregate_repo_result_multiple_repos():
    """Test aggregating multiple repo results."""
    all_repos: list[str] = []
    event_type_counts: dict[str, int] = {}
    all_coverage: dict[str, dict] = {}

    # First repo
    status1 = {
        "repo": "owner1/repo1",
        "open_issues_count": 5,
        "open_prs_count": 3,
        "recent_activity": [],
    }
    commits1 = {"commits": [{"sha": "a"}, {"sha": "b"}]}

    _aggregate_repo_result(
        "owner1",
        "repo1",
        status1,
        commits1,
        all_repos,
        event_type_counts,
        all_coverage,
    )

    # Second repo
    status2 = {
        "repo": "owner2/repo2",
        "open_issues_count": 10,
        "open_prs_count": 2,
        "recent_activity": [],
    }
    commits2 = {"commits": [{"sha": "x"}, {"sha": "y"}, {"sha": "z"}]}

    _aggregate_repo_result(
        "owner2",
        "repo2",
        status2,
        commits2,
        all_repos,
        event_type_counts,
        all_coverage,
    )

    assert all_repos == ["owner1/repo1", "owner2/repo2"]
    assert event_type_counts == {"Commit": 5, "Issue": 15, "PullRequest": 5}
    assert all_coverage["owner1/repo1"] == {
        "commit_count": 2,
        "open_issues_count": 5,
        "open_prs_count": 3,
    }
    assert all_coverage["owner2/repo2"] == {
        "commit_count": 3,
        "open_issues_count": 10,
        "open_prs_count": 2,
    }


def test_aggregate_repo_result_zero_events():
    """Test aggregating repo with no events."""
    all_repos: list[str] = []
    event_type_counts: dict[str, int] = {}
    all_coverage: dict[str, dict] = {}

    status = {
        "repo": "owner/repo",
        "open_issues_count": 0,
        "open_prs_count": 0,
        "recent_activity": [],
    }
    commits = {"commits": []}

    _aggregate_repo_result(
        "owner",
        "repo",
        status,
        commits,
        all_repos,
        event_type_counts,
        all_coverage,
    )

    assert all_repos == ["owner/repo"]
    assert event_type_counts == {}  # No events
    assert all_coverage["owner/repo"] == {
        "commit_count": 0,
        "open_issues_count": 0,
        "open_prs_count": 0,
    }
